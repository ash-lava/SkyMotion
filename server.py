"""SkyMotion: IRSA SIA2-backed SPHEREx observation explorer."""
import re, io, os, math, time, hashlib, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import numpy as np
import requests
from astropy.io import fits
from astropy.table import Table
from astropy.time import Time
from astropy.wcs import WCS
from astropy.nddata import Cutout2D
from astropy.coordinates import SkyCoord
import astropy.units as u
from PIL import Image
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/'cache'; CACHE.mkdir(exist_ok=True)
app=FastAPI(title='SkyMotion real SPHEREx API')
SESS=requests.Session(); SESS.headers['User-Agent']='SkyMotion-SPHEREx-Hackathon/1.0 (IRSA SIA2 client)'
# Candidate IRSA SIA2 collections. Each is probed at runtime; only ones IRSA answers are searched.
# New release? SPHEREX_COLLECTIONS=spherex_qr,spherex_qr2,<new>
CANDIDATES=os.environ.get('SPHEREX_COLLECTIONS','spherex_qr,spherex_qr2,spherex_qr3,spherex_dr1,spherex_qr_deep').split(',')
COLLECTIONS=tuple(CANDIDATES)
CACHE_TTL=int(os.environ.get('CACHE_TTL','21600'))
lock=threading.Lock()

_PROBE={'t':0,'ok':[],'bad':{}}
def live_collections(force=False):
    if force or time.time()-_PROBE['t']>3600:
        def probe(c):
            r=SESS.get('https://irsa.ipac.caltech.edu/SIA',params={'COLLECTION':c,'POS':'CIRCLE 127.69444 -39.17760 0.01','RESPONSEFORMAT':'votable'},timeout=30)
            r.raise_for_status();Table.read(io.BytesIO(r.content),format='votable')
        ok=[];bad={}
        with ThreadPoolExecutor(max_workers=len(CANDIDATES)) as pool:
            fs={pool.submit(probe,c):c for c in CANDIDATES}
            for f in as_completed(fs):
                try:f.result();ok.append(fs[f])
                except Exception as e:bad[fs[f]]=f'{type(e).__name__}: {str(e)[:90]}'
        _PROBE.update(t=time.time() if ok else 0,ok=[c for c in CANDIDATES if c in ok],bad=bad)
    return _PROBE['ok'] or list(CANDIDATES)  # if nothing answered, try all so real errors surface

def get_table(ra,dec,radius,collection):
    resp=SESS.get('https://irsa.ipac.caltech.edu/SIA',params={'COLLECTION':collection,'POS':f'CIRCLE {ra:.7f} {dec:.7f} {radius:.6f}','RESPONSEFORMAT':'votable'},timeout=75)
    resp.raise_for_status()
    table=Table.read(io.BytesIO(resp.content),format='votable')
    return table

def strval(row,key,default=''):
    try:
        v=row[key]
        if np.ma.is_masked(v): return default
        return str(v)
    except (KeyError,ValueError): return default

def floatval(row,key,default=None):
    try:
        v=float(row[key]); return v if math.isfinite(v) else default
    except (KeyError,TypeError,ValueError): return default

def mjd_to_iso(mjd):
    try: return Time(mjd,format='mjd').isot[:19]+'Z'
    except Exception: return ''

def key_for(ra,dec,radius,detector,limit):
    return hashlib.sha256(f'{",".join(CANDIDATES)}:{ra:.6f}:{dec:.6f}:{radius:.6f}:{detector}:{limit}'.encode()).hexdigest()[:24]

@app.get('/api/archive')
def archive(refresh:bool=False):
    live_collections(refresh);return {'live':_PROBE['ok'],'unavailable':_PROBE['bad'],'checked':_PROBE['t']}

@app.get('/api/health')
def health():return {'ok':True,'archive':'NASA/IPAC IRSA SIA2','collections':CANDIDATES}

@app.get('/api/observations')
def observations(ra:float=Query(...,ge=0,le=360),dec:float=Query(...,ge=-90,le=90),fov:float=Query(3,ge=1,le=12),detector:str='D2',limit:int=Query(32,ge=2,le=80),refresh:bool=False):
    if detector not in ('all','D1','D2','D3','D4','D5','D6'):raise HTTPException(400,'Invalid detector')
    radius=fov/120 # half field in arcmin -> degrees
    key=key_for(ra,dec,radius,detector,limit)
    path=CACHE/f'{key}.json'
    if path.exists() and not refresh and time.time()-path.stat().st_mtime<CACHE_TTL:
        import json
        return json.loads(path.read_text())
    rows,total,warnings=search(ra,dec,radius,detector,limit)
    payload={'observations':rows,'total':total,'warnings':warnings,'key':key,'source':'NASA/IPAC IRSA SIA2','real':True,'fov_arcmin':fov,'detector':detector}
    import json
    if rows or not warnings:path.write_text(json.dumps(payload))  # never cache a failed search
    return payload

def find_url(key,index):
    import json
    p=CACHE/f'{key}.json'
    if not p.exists():raise HTTPException(404,'Search expired. Search again.')
    data=json.loads(p.read_text())
    rows=data['observations']
    if index<0 or index>=len(rows):raise HTTPException(404,'Observation not found')
    # The URLs are deliberately not persisted in the browser; resolve the exact row again.
    # SIA2 row ordering is deterministic after sorting by timestamp, band and obs_id.
    # Cache URLs in a server-side companion file during search instead.
    q=CACHE/f'{key}.urls.json'
    if not q.exists():raise HTTPException(404,'Image links unavailable; refresh search')
    urls=json.loads(q.read_text())
    return urls[index],rows[index]

# Wrap the search to keep a private URL map, never trust URLs supplied by browsers.
def search(ra,dec,radius,detector,limit):
    rows=[];warnings=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(get_table,ra,dec,radius,c):c for c in live_collections()}
        for future in as_completed(futures):
            collection=futures[future]
            try:
                for r in future.result():
                    band=strval(r,'energy_bandpassname')
                    if detector!='all' and band.upper()!=f'SPHEREX-{detector}':continue
                    url=strval(r,'access_url')
                    if not url.startswith('https://irsa.ipac.caltech.edu/'):continue
                    rows.append({'id':strval(r,'obs_id'),'collection':collection,'band':band,'mjd':floatval(r,'t_min'),'date':mjd_to_iso(floatval(r,'t_min')),'url':url,'em_min':floatval(r,'em_min'),'em_max':floatval(r,'em_max'),'exptime':floatval(r,'t_exptime')})
            except Exception as e:warnings.append(f'{collection}: {type(e).__name__}: {str(e)[:160]}')
    rows.sort(key=lambda x:(x['mjd'] if x['mjd'] is not None else 1e12,x['band'],x['id']))
    total=len(rows)
    if len(rows)>limit:
        inds=np.unique(np.linspace(0,len(rows)-1,limit,dtype=int));rows=[rows[int(i)] for i in inds]
    key=key_for(ra,dec,radius,detector,limit)
    import json
    (CACHE/f'{key}.urls.json').write_text(json.dumps([r['url'] for r in rows]))
    return rows,total,warnings

def _image_data_raw(key,index,ra,dec,fov):
    url,meta=find_url(key,index)
    # IRSA IBE cutout API: append center and size query to a vetted IRSA access URL.
    # Retrieve only a small cutout rather than multi-hundred-MB full-frame files.
    params={'center':f'{ra:.7f},{dec:.7f}d','size':f'{fov/60:.7f}'}
    r=SESS.get(url,params=params,timeout=100)
    r.raise_for_status()
    if len(r.content)>40_000_000:raise ValueError('Cutout too large; choose a smaller field')
    with fits.open(io.BytesIO(r.content),memmap=False,ignore_missing_simple=True) as hdul:
        candidates=[]
        for h in hdul:
            if h.data is not None and getattr(h.data,'ndim',0)==2 and h.data.size>100:
                name=h.name.upper()
                rank=0 if name in ('IMAGE','SCI','PRIMARY') else 1
                candidates.append((rank,h))
        if not candidates:raise ValueError('No 2D image data in FITS cutout')
        h=sorted(candidates,key=lambda x:x[0])[0][1]
        data=np.array(h.data,dtype=np.float32)
        try:
            wcs=WCS(h.header).celestial
            target=SkyCoord(ra,dec,unit='deg')
            cut=Cutout2D(data,target,(min(128,data.shape[0]),min(128,data.shape[1])),wcs=wcs,mode='partial',fill_value=np.nan)
            data=cut.data;_WCS[(key,index)]=cut.wcs
        except Exception:pass
    return data,meta

@app.get('/api/frame/{key}/{index}.png')
def frame(key:str,index:int,ra:float=Query(...,ge=0,le=360),dec:float=Query(...,ge=-90,le=90),fov:float=Query(3,ge=1,le=12)):
    if not (len(key)==24 and all(c in '0123456789abcdef' for c in key)):raise HTTPException(400,'Invalid key')
    try:
        data,_=image_data(key,index,ra,dec,fov)
        good=data[np.isfinite(data)]
        if good.size<20:raise ValueError('No valid pixels')
        low,high=np.percentile(good,[5,99.5]); high=max(high,low+1e-8)
        arr=np.clip((np.nan_to_num(data,nan=low)-low)/(high-low),0,1)
        arr=np.uint8(np.sqrt(arr)*255)
        buf=io.BytesIO();Image.fromarray(arr,mode='L').resize((512,512)).save(buf,format='PNG')
        return Response(buf.getvalue(),media_type='image/png',headers={'Cache-Control':'public, max-age=86400'})
    except HTTPException:raise
    except Exception as e:raise HTTPException(502,f'NASA image retrieval/processing failed: {str(e)[:200]}')

@app.get('/api/photometry/{key}')
def photometry(key:str,ra:float=Query(...,ge=0,le=360),dec:float=Query(...,ge=-90,le=90),fov:float=Query(3,ge=1,le=12),max_frames:int=Query(18,ge=2,le=32)):
    import json
    p=CACHE/f'{key}.json'
    if not p.exists():raise HTTPException(404,'Run a search first')
    observations=json.loads(p.read_text())['observations']
    indices=np.unique(np.linspace(0,len(observations)-1,min(max_frames,len(observations)),dtype=int))
    results=[]
    for i in indices:
        try:
            data,meta=image_data(key,int(i),ra,dec,fov)
            # A simple *uncalibrated* central aperture proxy; not a scientific light curve.
            yy,xx=np.indices(data.shape);cy,cx=(np.array(data.shape)-1)/2
            rr=np.hypot(xx-cx,yy-cy)
            annulus=data[(rr>=9)&(rr<=15)&np.isfinite(data)]
            aperture=data[(rr<=4)&np.isfinite(data)]
            if len(annulus)<10 or len(aperture)<10:continue
            background=float(np.median(annulus))
            proxy=float(np.sum(aperture-background))
            results.append({'index':int(i),'date':meta['date'],'band':meta['band'],'proxy':proxy,'background':background})
        except Exception as e:results.append({'index':int(i),'date':observations[int(i)]['date'],'error':str(e)[:100]})
    return {'measurements':results,'type':'uncalibrated_aperture_proxy','warning':'Exploratory central-pixel aperture only; not calibrated photometry. SPHEREx has a wavelength gradient across the detector. Compare only compatible wavelength, geometry, and quality observations.'}

_WCS={};_FR={};_GAIA={}
def image_data(key,index,ra,dec,fov):
    k=(key,index,round(ra,5),round(dec,5),fov)
    if k not in _FR:
        if len(_FR)>80:_FR.pop(next(iter(_FR)))
        _FR[k]=_image_data_raw(key,index,ra,dec,fov)  # frame + overlay share one IRSA fetch
    return _FR[k]

def gaia_stars(ra,dec,radius):
    k=(round(ra,4),round(dec,4),round(radius,5))
    if k not in _GAIA:
        q=f"SELECT TOP 300 source_id,ra,dec,pmra,pmdec,phot_g_mean_mag FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.6f},{dec:.6f},{radius:.6f})) ORDER BY phot_g_mean_mag"
        r=SESS.post('https://gea.esac.esa.int/tap-server/tap/sync',data={'REQUEST':'doQuery','LANG':'ADQL','FORMAT':'json','QUERY':q},timeout=60);r.raise_for_status()
        j=r.json();cols=[m['name'] for m in j['metadata']];_GAIA[k]=[dict(zip(cols,x)) for x in j['data']]
    return _GAIA[k]

@app.get('/api/resolve')
def resolve(q:str=Query(...,min_length=2,max_length=80)):
    """Name (SIMBAD/NED via CDS), decimal degrees, or sexagesimal -> RA/Dec in degrees."""
    q=q.strip()
    try:
        if re.fullmatch(r'[-+]?\d+(\.\d+)?[\s,]+[-+]?\d+(\.\d+)?',q):
            a,d=[float(x) for x in re.split(r'[\s,]+',q)];c=SkyCoord(a,d,unit='deg')
        elif re.fullmatch(r'[\d\s:.+\-hmsd,]+',q):c=SkyCoord(q.replace(',',' '),unit=(u.hourangle,u.deg))
        else:c=SkyCoord.from_name(q)
        return {'ra':round(float(c.ra.deg),6),'dec':round(float(c.dec.deg),6),'query':q}
    except Exception:raise HTTPException(404,f'Could not resolve "{q}". Try a SIMBAD name or coordinates.')

@app.get('/api/overlay/{key}/{index}.json')
def overlay(key:str,index:int,ra:float=Query(...,ge=0,le=360),dec:float=Query(...,ge=-90,le=90),fov:float=Query(3,ge=1,le=12)):
    """Gaia DR3 sources, proper-motion propagated from J2016.0 to this exposure, in the frame's own WCS."""
    if not (len(key)==24 and all(c in '0123456789abcdef' for c in key)):raise HTTPException(400,'Invalid key')
    try:
        data,meta=image_data(key,index,ra,dec,fov);wcs=_WCS.get((key,index))
        if wcs is None:return {'stars':[],'note':'Frame has no usable WCS; overlay unavailable.'}
        h,w=data.shape;dt=((meta.get('mjd') or 57388.0)-57388.0)/365.25;out=[]
        for st in gaia_stars(ra,dec,fov/120+0.05):  # margin so fast movers still land in frame
            pa=st['pmra'] or 0;pd=st['pmdec'] or 0
            d=st['dec']+pd*dt/3.6e6;a=st['ra']+pa*dt/3.6e6/max(math.cos(math.radians(st['dec'])),1e-6)
            x,y=wcs.world_to_pixel(SkyCoord(a,d,unit='deg'))
            if -0.5<=x<w-0.5 and -0.5<=y<h-0.5:out.append({'x':float(x+.5)/w,'y':float(y+.5)/h,'g':st['phot_g_mean_mag'],'pm':math.hypot(pa,pd),'id':str(st['source_id'])})
        return {'stars':out,'mjd':meta.get('mjd'),'source':'Gaia DR3 (ESA), propagated by proper motion'}
    except HTTPException:raise
    except Exception as e:raise HTTPException(502,f'Gaia overlay failed: {str(e)[:160]}')

ASSETS={'style.css','app.js','react.production.min.js','react-dom.production.min.js','htm.js'}
@app.get('/static/{name}')
@app.get('/static/vendor/{name}')
def asset(name:str):
    if name not in ASSETS:raise HTTPException(404,'Not found')  # only whitelisted front-end files are public
    return FileResponse(ROOT/name)

@app.get('/')
def home():return FileResponse(ROOT/'index.html')
