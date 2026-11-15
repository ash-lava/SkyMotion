"""Static real-data color example; dates differ, so this is not color playback."""
from pathlib import Path
import sys,json,io,hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
import archive_client as archive
import server
def main():
    import argparse
    parser=argparse.ArgumentParser(description='Regenerate the documented, mixed-date SPHEREx RGB example from IRSA FITS cutouts.')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    records=json.loads((ROOT/'docs/spherex-color-provenance.json').read_text())['observations']
    queries=[{'detector':r['detector'],'rows':[r]} for r in records]
    arrays={};metadata=[];grid=server.target_wcs(210.80227,54.34895,6)
    for detector in ('D1','D3','D6'):
     row=next(x for x in queries if x['detector']==detector)['rows'][0]
     if not archive.safe_image_url(row['url']):raise ValueError('Expected an IRSA SPHEREx science URL')
     raw=archive.fetch_bytes(row['url'],{'center':'210.80227000,54.34895000d','size':'0.15000000'},timeout=55,max_bytes=40000000)
     (out/f'color-{detector}.fits').write_bytes(raw)
     with fits.open(io.BytesIO(raw),memmap=False) as hdus:
      h=next(h for h in hdus if h.name.upper() in ('SCI','IMAGE') and h.data is not None and h.data.ndim==2)
      wcs=WCS(h.header,fobj=hdus).celestial
      array=server.align_array(np.asarray(h.data,dtype=np.float32),wcs,grid)
      x,y=wcs.world_to_pixel(SkyCoord(210.80227,54.34895,unit='deg'))
      sp=WCS(h.header,fobj=hdus,key='W');sp.sip=None
      wave,_=sp.pixel_to_world(x,y);wave=float(wave.to_value(u.um))
      metadata.append({**row,'detector':detector,'center_wavelength_um':wave,'coverage':float(np.isfinite(array).mean()),'unit':h.header.get('BUNIT'),'sha256_download':hashlib.sha256(raw).hexdigest()})
      arrays[detector]=array
      print(detector,row['date'],wave,metadata[-1]['coverage'],flush=True)
    common=np.logical_and.reduce([np.isfinite(arrays[d]) for d in ('D1','D3','D6')])
    channels=[]
    for d in ('D6','D3','D1'):
     a=arrays[d];lo,hi=np.percentile(a[np.isfinite(a)],[5,99.5]);hi=max(hi,lo+1e-8)
     channels.append(np.uint8(np.sqrt(np.clip((np.where(np.isfinite(a),a,lo)-lo)/(hi-lo),0,1))*255))
    rgba=np.flipud(np.stack((*channels,common.astype(np.uint8)*255),axis=-1))
    Image.fromarray(rgba).save(out/'spherex-color-data.png')
    canvas=Image.new('RGB',(704,872),'#090b0b');draw=ImageDraw.Draw(canvas)
    fontpath='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    try:
        font=ImageFont.truetype(fontpath,15);title=ImageFont.truetype(fontpath,22);small=ImageFont.truetype(fontpath,12)
    except OSError:
        font=ImageFont.load_default(size=15);title=ImageFont.load_default(size=22);small=ImageFont.load_default(size=12)
    draw.text((32,20),'SPHEREx infrared color preview',fill='#eadfbf',font=title)
    draw.text((32,55),'M101 | 6 arcmin | real IRSA science data',fill='#c8c4b6',font=font)
    draw.text((32,80),'Mixed observation dates: 9–22 May 2025',fill='#d8bf80',font=font)
    # Clip the hatched field to the image square before compositing the real data.
    bg=Image.new('RGB',(576,576),'#151816');bd=ImageDraw.Draw(bg)
    for x in range(-576,576,9):bd.line((x,0,x+576,576),fill='#746b50',width=1)
    canvas.paste(bg,(64,120));canvas.paste(Image.fromarray(rgba).resize((576,576),Image.Resampling.NEAREST),(64,120),Image.fromarray(rgba).getchannel('A').resize((576,576),Image.Resampling.NEAREST))
    # Clear margins so hatching is confined to the data field.
    draw.rectangle((0,111,63,705),fill='#090b0b');draw.rectangle((640,111,703,705),fill='#090b0b')
    for i,(d,color,label) in enumerate((('D6','#ec9a92','Red'),('D3','#9bd0a4','Green'),('D1','#99b6ed','Blue'))):
     m=next(x for x in metadata if x['detector']==d)
     draw.text((32,714+i*29),f'{label}: {d}, {m["center_wavelength_um"]:.3f} µm, {m["date"][:10]}',fill=color,font=font)
    draw.text((32,810),'Qualitative independent stretches; mixed dates can mimic colors of motion.',fill='#b8b4a8',font=small)
    draw.text((32,833),f'Common valid coverage: {100*common.mean():.1f}% | NASA / JPL / Caltech / IPAC',fill='#b8b4a8',font=small)
    canvas.save(out/'spherex-color-preview.png')
    (out/'spherex-color-provenance.json').write_text(json.dumps({'target':'M101','ra':210.80227,'dec':54.34895,'fov_arcmin':6,'channels':{'red':'D6','green':'D3','blue':'D1'},'observations':metadata,'common_coverage':float(common.mean()),'display':'Per-channel 5–99.5 percentile square-root stretch; north up, east left.','warning':'This is a static mixed-date feasibility preview, not simultaneous color or color playback.'},indent=2))
    print('Saved actual SPHEREx color feasibility preview.',flush=True)

if __name__=='__main__':
    main()
