"""sphere360: a real sky atlas and WCS-aligned SPHEREx sequence viewer."""
import hashlib
import io
import json
import math
import os
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import date as CalendarDate
from pathlib import Path
from urllib.parse import quote

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, RedirectResponse
from PIL import Image

import archive_client as archive
import comparison
import infrared_color

ROOT = Path(__file__).resolve().parent
CACHE = Path(os.getenv('CACHE_DIR', str(ROOT / 'cache')))
CACHE.mkdir(parents=True, exist_ok=True)
CACHE_TTL = int(os.getenv('CACHE_TTL', '21600'))
VERSION = '2.1.0'
app = FastAPI(title='sphere360', version=VERSION)
from sky_service import router as sky_router
app.include_router(sky_router)
STATE_LOCK = threading.RLock()
IMAGE_LOCK = threading.Lock()  # bound memory / simultaneous FITS decoding on small Render instances
FRAMES, GAIA = OrderedDict(), OrderedDict()
STATUS = {'checked': None, 'live': [], 'unavailable': {}, 'tap': None, 'search_method': None}
SIZE = 192


def valid_key(key):
    if not re.fullmatch(r'[a-f0-9]{24}', key):
        raise HTTPException(400, 'Invalid search key.')


def key_for(ra, dec, fov, detector, limit, start=None, end=None):
    query = [VERSION, archive.COLLECTIONS, ra, dec, fov, detector, limit, str(start), str(end)]
    return hashlib.sha256(json.dumps(query).encode()).hexdigest()[:24]


def write_cache(key, payload):
    temp = CACHE / f'{key}.{uuid.uuid4().hex}.tmp'
    try:
        temp.write_text(json.dumps(payload, allow_nan=False), encoding='utf-8')
        temp.replace(CACHE / f'{key}.json')
    finally:
        temp.unlink(missing_ok=True)
    # Metadata snapshots are immutable by artifact order; only the small lookup pointer changes.
    with STATE_LOCK:
        files = sorted(CACHE.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[300:]:
            path.unlink(missing_ok=True)
        for ref in CACHE.glob('*.ref'):
            try:
                if not (CACHE / (ref.read_text().strip() + '.json')).exists():
                    ref.unlink(missing_ok=True)
            except OSError:
                pass


def read_search(key):
    valid_key(key)
    path = CACHE / f'{key}.json'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(404, 'Search expired. Load this patch again.')


def public_payload(payload):
    return {**payload, 'observations': [{**{k: v for k, v in row.items() if k != 'url'},
                                       'archive_url': row.get('url')} for row in payload['observations']]}


def combined_search(base, extra):
    """Join immutable live-search snapshots, preserving independent search windows."""
    if not base:
        return public_payload(extra)
    rows = list({r['url']: r for r in base['observations'] + extra['observations']}.values())
    rows.sort(key=lambda r: (r['mjd'] if r.get('mjd') is not None else float('inf'), r['band'], r['id']))
    total = len(rows)
    if total > 64:
        rows = [rows[round(i * (total - 1) / 63)] for i in range(64)]
    fields = ('date_range', 'queried_at', 'search_method', 'query_limits', 'sampling_limited')
    windows = base.get('search_windows', [{k: base.get(k) for k in fields}])
    windows = windows + [{k: extra.get(k) for k in fields}]
    warnings = list(dict.fromkeys(base['warnings'] + extra['warnings']))
    if total > 64:
        warnings.append('Combined searches exceed 64 frames; 64 were selected across the returned dates.')
    times = [r['mjd'] for r in rows if r.get('mjd') is not None]
    key = hashlib.sha256((VERSION + base['key'] + extra['key'] + json.dumps(rows, sort_keys=True)).encode()).hexdigest()[:24]
    payload = {**extra, 'key': key, 'observations': rows, 'total': total, 'warnings': warnings,
               'search_windows': windows, 'collections': sorted(set(base['collections'] + extra['collections'])),
               'search_method': ' + '.join(dict.fromkeys((base['search_method'], extra['search_method']))),
               'sampling_limited': base.get('sampling_limited', False) or extra.get('sampling_limited', False) or total > 64,
               'total_lower_bound': base.get('total_lower_bound', False) or extra.get('total_lower_bound', False) or total > 64,
               'time_span_days': max(times) - min(times) if times else None}
    write_cache(key, payload)
    return public_payload(payload)


@app.get('/api/health')
def health():
    return {'ok': True, 'version': VERSION, 'archive': 'NASA/IPAC IRSA SIA2 + TAP', 'collections': archive.COLLECTIONS}


@app.get('/api/archive')
def archive_status():
    # This reports the last real query; it does not send five speculative probes.
    with STATE_LOCK:
        return {**STATUS, 'configured': archive.COLLECTIONS,
                'status': 'unchecked' if STATUS['checked'] is None else ('ready' if STATUS['live'] or (STATUS.get('tap') or {}).get('ok') else 'unavailable')}


@app.get('/api/observations')
def observations(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
                 fov: float = Query(3, ge=1, le=12), detector: str = 'D2',
                 limit: int = Query(24, ge=2, le=64), refresh: bool = False,
                 start: CalendarDate | None = None, end: CalendarDate | None = None,
                 append: str | None = None):
    if detector not in ('all', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6'):
        raise HTTPException(400, 'Choose a detector from D1 to D6.')
    if start and end and start > end:
        raise HTTPException(400, 'Start date must be on or before end date (UTC).')
    anchor = CalendarDate(1858, 11, 17).toordinal()
    time_range = ((start.toordinal() - anchor) if start else None,
                  (end.toordinal() + 1 - anchor) if end else None) if start or end else None
    base = read_search(append) if append else None
    if base and any(base.get(k) != value for k, value in (('ra', ra), ('dec', dec), ('fov_arcmin', fov), ('detector', detector))):
        raise HTTPException(400, 'Additional dates must use the same coordinates, field and detector.')
    if base and len(base.get('search_windows', [])) >= 20:
        raise HTTPException(400, 'This sequence already combines 20 searches. Start a new sequence.')
    lookup_key = key_for(ra, dec, fov, detector, limit, start, end)
    if not refresh:
        try:
            cached_key = (CACHE / f'{lookup_key}.ref').read_text().strip()
            path = CACHE / f'{cached_key}.json'
            if time.time() - path.stat().st_mtime < CACHE_TTL:
                return combined_search(base, read_search(cached_key))
        except (OSError, HTTPException):
            pass
    diagnostics = {}
    try:
        # A bounded live search finds footprints covering the center; fov sets cutout width.
        rows, total, warnings, live, failed = archive.search(
            ra, dec, fov * math.sqrt(2) / 120, detector, limit, diagnostics=diagnostics,
            **({'time_range': time_range} if time_range else {}))
    except archive.ArchiveError as exc:
        with STATE_LOCK:
            STATUS.update(checked=time.time(), live=[], unavailable=diagnostics.get('unavailable') or {c: str(exc) for c in archive.COLLECTIONS},
                          tap=diagnostics.get('tap'), search_method=None)
        raise HTTPException(503, {'code': 'SPHEREX_UNAVAILABLE', 'message': str(exc)}, headers={'Retry-After': '30'})
    method = diagnostics.get('method', 'SIA2')
    with STATE_LOCK:
        STATUS.update(checked=time.time(), live=live, unavailable=failed,
                      tap=diagnostics.get('tap'), search_method=method)
    # A changed set/order of artifacts gets new frame URLs, even for identical field settings.
    key = hashlib.sha256((lookup_key + json.dumps(rows, sort_keys=True)).encode()).hexdigest()[:24]
    times = [r['mjd'] for r in rows if r.get('mjd') is not None]
    payload = {'key': key, 'observations': rows, 'total': total, 'warnings': warnings,
               'source': 'NASA/IPAC IRSA SPHEREx', 'search_method': method, 'real': True,
               'ra': ra, 'dec': dec, 'fov_arcmin': fov, 'detector': detector,
               'collections': live, 'sampling_limited': diagnostics.get('sampling_limited', False),
               'total_lower_bound': bool(failed) or diagnostics.get('sampling_limited', False),
               'query_limits': diagnostics.get('query_limits', {}), 'queried_at': time.time(),
               'date_range': {'start': start.isoformat() if start else None, 'end': end.isoformat() if end else None, 'timezone': 'UTC'},
               'time_span_days': max(times) - min(times) if times else None,
               'alignment': 'Common north-up, east-left ICRS TAN grid; bilinear interpolation.'}
    write_cache(key, payload)
    ref = CACHE / f'{lookup_key}.ref'
    if not warnings or diagnostics.get('complete_search', False):
        temp = CACHE / f'{lookup_key}.{uuid.uuid4().hex}.tmp'
        try:
            temp.write_text(key)
            temp.replace(ref)
        finally:
            temp.unlink(missing_ok=True)
    else:
        # Preserve partial snapshots for their loaded frames, but retry the next search.
        ref.unlink(missing_ok=True)
    return combined_search(base, payload)


def target_wcs(ra, dec, fov):
    from astropy.wcs import WCS
    result = WCS(naxis=2)
    result.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    result.wcs.crval = [ra, dec]
    result.wcs.crpix = [(SIZE + 1) / 2, (SIZE + 1) / 2]
    scale = fov / 60 / SIZE
    result.wcs.cdelt = [-scale, scale]
    return result


def align_array(data, source_wcs, destination_wcs, size=SIZE):
    from scipy.ndimage import map_coordinates
    yy, xx = np.indices((size, size), dtype=float)
    sky = destination_wcs.pixel_to_world(xx, yy)
    sx, sy = source_wcs.world_to_pixel(sky)
    finite = np.isfinite(data)
    values = map_coordinates(np.where(finite, data, 0.0), [sy, sx], order=1, mode='constant', cval=0.0, prefilter=False)
    weights = map_coordinates(finite.astype(float), [sy, sx], order=1, mode='constant', cval=0.0, prefilter=False)
    result = np.full(values.shape, np.nan, dtype=np.float32)
    np.divide(values, weights, out=result, where=weights > 0.99)
    return result


def image_data(key, index):
    data = read_search(key)
    if index < 0 or index >= len(data['observations']):
        raise HTTPException(404, 'Exposure not found.')
    row = data['observations'][index]
    if not archive.safe_image_url(row['url']):
        raise HTTPException(400, 'Invalid archive image link. Load this patch again.')
    # Include URL: refreshing a query cannot accidentally reuse a different exposure.
    identity = (key, row['url'])
    with IMAGE_LOCK:
        if identity in FRAMES:
            FRAMES.move_to_end(identity)
            return FRAMES[identity]
        from astropy.io import fits
        from astropy.wcs import WCS
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        raw = archive.fetch_bytes(row['url'], {'center': f"{data['ra']:.8f},{data['dec']:.8f}d",
                    'size': f"{data['fov_arcmin'] * 1.5 / 60:.8f}"}, timeout=55, max_bytes=40_000_000)
        with fits.open(io.BytesIO(raw), memmap=False) as hdus:
            science = next((h for h in hdus if h.name.upper() in ('IMAGE', 'SCI') and h.data is not None and h.data.ndim == 2), None)
            if science is None:
                raise archive.ArchiveError('The cutout has no science image.')
            source_wcs = WCS(science.header, fobj=hdus).celestial
            if not source_wcs.has_celestial:
                raise archive.ArchiveError('The cutout has no sky coordinates; it cannot be aligned safely.')
            grid = target_wcs(data['ra'], data['dec'], data['fov_arcmin'])
            array = align_array(np.asarray(science.data, dtype=np.float32), source_wcs, grid)
            info = {'wavelength_um': None, 'bandwidth_um': None, 'flagged_fraction': None,
                    'unit': None, 'native_unit': str(science.header.get('BUNIT', '')),
                    'version': str(hdus[0].header.get('VERSION', ''))}
            try:
                factor = u.Unit(info['native_unit']).to(u.MJy / u.sr)
                array *= factor
                info['unit'] = 'MJy/sr'
            except (ValueError, TypeError):
                pass
            center = SkyCoord(data['ra'], data['dec'], unit='deg')
            try:
                x, y = source_wcs.world_to_pixel(center)
                spectral = WCS(science.header, fobj=hdus, key='W')
                spectral.sip = None
                wavelength, bandwidth = spectral.pixel_to_world(x, y)
                wave = float(wavelength.to_value(u.um))
                if math.isfinite(wave):
                    info['wavelength_um'] = wave
                width = float(bandwidth.to_value(u.um))
                if math.isfinite(width) and width > 0:
                    info['bandwidth_um'] = width
                yy, xx = np.indices((SIZE, SIZE), dtype=float)
                sx, sy = source_wcs.world_to_pixel(grid.pixel_to_world(xx, yy))
                waves, widths = spectral.pixel_to_world(sx, sy)
                info['_wavelength_map'] = np.asarray(waves.to_value(u.um), dtype=np.float32)
                info['_bandwidth_map'] = np.asarray(widths.to_value(u.um), dtype=np.float32)
            except Exception:
                pass  # Do not invent wavelengths for products without usable spectral WCS.
            if 'FLAGS' in hdus and hdus['FLAGS'].data is not None:
                flags = hdus['FLAGS']
                if flags.data.shape == science.data.shape:
                    from scipy.ndimage import map_coordinates
                    yy, xx = np.indices((SIZE, SIZE), dtype=float)
                    sx, sy = source_wcs.world_to_pixel(grid.pixel_to_world(xx, yy))
                    mask = map_coordinates((flags.data != 0).astype(float), [sy, sx], order=0, mode='constant', cval=np.nan)
                    valid = np.isfinite(mask) & np.isfinite(array)
                    if np.any(valid):
                        info['flagged_fraction'] = float(mask[valid].mean())
        if np.isfinite(array).sum() < 20:
            raise archive.ArchiveError('This exposure does not cover enough of the selected patch. Try another frame.')
        result = (array, row, grid, info)
        FRAMES[identity] = result
        while len(FRAMES) > 48:
            FRAMES.popitem(last=False)
        return result


def get_image(key, index):
    try:
        return image_data(key, index)
    except HTTPException:
        raise
    except archive.ArchiveError as exc:
        raise HTTPException(502, str(exc))
    except Exception:
        raise HTTPException(502, 'The SPHEREx cutout could not be processed. Retry this frame or select another exposure.')


@app.get('/api/frame/{key}/{index}.png')
def frame(key: str, index: int):
    array, _, _, _ = get_image(key, index)
    finite = np.isfinite(array)
    valid = array[finite]
    low, high = np.percentile(valid, [5, 99.5])
    high = max(high, low + 1e-8)
    intensity = np.clip((np.where(finite, array, low) - low) / (high - low), 0, 1)
    # FITS y increases upward. Flip PNG so north remains at the top.
    gray = np.flipud(np.uint8(np.sqrt(intensity) * 255))
    # Missing science pixels stay transparent, distinct from valid dark pixels.
    alpha = np.flipud(finite.astype(np.uint8) * 255)
    rgba = np.stack((gray, gray, gray, alpha), axis=-1)
    buffer = io.BytesIO()
    Image.fromarray(rgba).save(buffer, format='PNG')
    return Response(buffer.getvalue(), media_type='image/png', headers={'Cache-Control': 'no-store'})


@app.get('/api/frame-info/{key}/{index}')
def frame_info(key: str, index: int):
    array, row, _, info = get_image(key, index)
    valid_pixels = int(np.isfinite(array).sum())
    return {**{k: v for k, v in row.items() if k != 'url'}, **{k: v for k, v in info.items() if not k.startswith('_')},
            'coverage': valid_pixels / array.size, 'valid_pixels': valid_pixels,
            'missing_pixels': int(array.size - valid_pixels), 'total_pixels': int(array.size),
            'coverage_definition': 'Fraction of the aligned patch with finite science values; quality flags are separate.',
            'stretch': 'Independent 5–99.5 percentile square-root stretch.'}


@app.get('/api/cutout/{key}/{index}')
def original_cutout(key: str, index: int):
    data = read_search(key)
    if index < 0 or index >= len(data['observations']):
        raise HTTPException(404, 'Exposure not found.')
    url = data['observations'][index]['url']
    if not archive.safe_image_url(url):
        raise HTTPException(400, 'Invalid archive image link.')
    from urllib.parse import urlencode
    params = urlencode({'center': f"{data['ra']:.8f},{data['dec']:.8f}d", 'size': f"{data['fov_arcmin'] * 1.5 / 60:.8f}"})
    return RedirectResponse(url + '?' + params, headers={'Cache-Control': 'no-store'})


def comparison_data(key, a, b, background):
    try:
        return comparison.prepare(get_image(key, a), get_image(key, b), a, b, background=background)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get('/api/comparison/{key}')
def compare_info(key: str, a: int = Query(..., ge=0), b: int = Query(..., ge=0), background: bool = True):
    result = comparison_data(key, a, b, background)
    data = read_search(key)
    return {**result['metadata'], 'key': key, 'source': 'NASA/IPAC IRSA SPHEREx',
            'ra': data['ra'], 'dec': data['dec'], 'fov_arcmin': data['fov_arcmin']}


@app.get('/api/comparison/{key}/image.png')
def compare_image(key: str, a: int = Query(..., ge=0), b: int = Query(..., ge=0),
                  view: str = 'a', background: bool = True):
    if view not in ('a', 'b', 'difference', 'mean'):
        raise HTTPException(400, 'Choose A, B, difference or mean.')
    try:
        raw = comparison.png(comparison_data(key, a, b, background), view)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return Response(raw, media_type='image/png', headers={'Cache-Control': 'no-store'})


@app.get('/api/comparison/{key}/data.fits')
def compare_fits(key: str, a: int = Query(..., ge=0), b: int = Query(..., ge=0),
                 operation: str = 'difference', background: bool = True):
    if operation not in ('difference', 'mean'):
        raise HTTPException(400, 'Choose difference or mean.')
    result = comparison_data(key, a, b, background)
    metadata = result['metadata']
    if not metadata['arithmetic_available']:
        raise HTTPException(422, ' '.join(metadata['reasons']))
    from astropy.io import fits
    header = result['grid'].to_header()
    header['BUNIT'] = 'MJy/sr'
    header['CREATOR'] = 'sphere360 ' + VERSION
    header['OPERAT'] = operation
    header['BGSUB'] = background
    header['BG_A'] = metadata['background_a']
    header['BG_B'] = metadata['background_b']
    header['SRC_A'] = str(metadata['a']['id'])
    header['SRC_B'] = str(metadata['b']['id'])
    header['HISTORY'] = metadata['wavelength_rule']
    header['HISTORY'] = 'Quick-look only. No PSF matching, error propagation or flag rejection.'
    buffer = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(result[operation].astype(np.float32), header),
                  fits.ImageHDU(result['mask'].astype(np.uint8), name='VALID')]).writeto(buffer)
    return Response(buffer.getvalue(), media_type='application/fits',
                    headers={'Content-Disposition': f'attachment; filename="sphere360-{operation}.fits"', 'Cache-Control': 'no-store'})


def color_data(red_key, red_index, green_key, green_index, blue_key, blue_index, allow_mixed_dates):
    keys=(red_key,green_key,blue_key)
    searches=[read_search(key) for key in keys]
    field=tuple(searches[0][k] for k in ('ra','dec','fov_arcmin'))
    if any(tuple(data[k] for k in ('ra','dec','fov_arcmin'))!=field for data in searches[1:]):
        raise HTTPException(400, 'Color channels must use the same sky coordinates and cutout size.')
    indices=(red_index,green_index,blue_index)
    for data,index in zip(searches,indices):
        if index < 0 or index >= len(data['observations']):
            raise HTTPException(404,'Color exposure not found.')
    times=[data['observations'][index].get('mjd') for data,index in zip(searches,indices)]
    if all(isinstance(v,(int,float)) and math.isfinite(v) for v in times):
        span=max(times)-min(times)
        if span>1 and not allow_mixed_dates:
            raise HTTPException(422,f'These channels are {span:.2f} days apart. Choose closer dates or explicitly allow mixed dates.')
    entries=[get_image(key,index) for key,index in zip(keys,indices)]
    try:
        raw,metadata=infrared_color.prepare(entries,indices,allow_mixed_dates=allow_mixed_dates)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    for label,key in zip(('red','green','blue'),keys):
        metadata['channels'][label]['key']=key
    return raw,{**metadata,'ra':field[0],'dec':field[1],'fov_arcmin':field[2]}


@app.get('/api/color')
def color_info(red_key: str, green_key: str, blue_key: str,
               red_index: int = Query(...,ge=0), green_index: int = Query(...,ge=0), blue_index: int = Query(...,ge=0),
               allow_mixed_dates: bool = False):
    return color_data(red_key,red_index,green_key,green_index,blue_key,blue_index,allow_mixed_dates)[1]


@app.get('/api/color/image.png')
def color_image(red_key: str, green_key: str, blue_key: str,
                red_index: int = Query(...,ge=0), green_index: int = Query(...,ge=0), blue_index: int = Query(...,ge=0),
                allow_mixed_dates: bool = False):
    raw,_=color_data(red_key,red_index,green_key,green_index,blue_key,blue_index,allow_mixed_dates)
    return Response(raw,media_type='image/png',headers={'Cache-Control':'no-store'})


def gaia_stars(ra, dec, radius):
    key = (ra, dec, radius)
    with STATE_LOCK:
        if key in GAIA:
            return GAIA[key]
    query = ("SELECT TOP 300 source_id,ra,dec,pmra,pmdec,phot_g_mean_mag FROM gaiadr3.gaia_source "
             f"WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.8f},{dec:.8f},{radius:.8f})) "
             "ORDER BY phot_g_mean_mag")
    raw = archive.fetch_bytes('https://gea.esac.esa.int/tap-server/tap/sync',
            {'REQUEST': 'doQuery', 'LANG': 'ADQL', 'FORMAT': 'json', 'QUERY': query}, timeout=30)
    payload = json.loads(raw)
    columns = [m['name'] for m in payload['metadata']]
    stars = [dict(zip(columns, row)) for row in payload['data']]
    with STATE_LOCK:
        GAIA[key] = stars
        while len(GAIA) > 24:
            GAIA.popitem(last=False)
    return stars


@app.get('/api/overlay/{key}/{index}.json')
def overlay(key: str, index: int):
    data = read_search(key)
    _, row, grid, _ = get_image(key, index)
    from astropy.coordinates import SkyCoord
    stars = []
    # Gaia DR3 reference epoch is J2016.0, JD 2457389.0 / MJD 57388.5.
    dt = ((row['mjd'] if row['mjd'] is not None else 57388.5) - 57388.5) / 365.25
    try:
        for star in gaia_stars(data['ra'], data['dec'], data['fov_arcmin'] * math.sqrt(2) / 120 + .05):
            pmra, pmdec = star['pmra'] or 0, star['pmdec'] or 0
            dec = star['dec'] + pmdec * dt / 3.6e6
            ra = star['ra'] + pmra * dt / (3.6e6 * max(math.cos(math.radians(star['dec'])), 1e-6))
            if not -90 <= dec <= 90:
                continue
            x, y = grid.world_to_pixel(SkyCoord(ra, dec, unit='deg'))
            if -.5 <= x < SIZE - .5 and -.5 <= y < SIZE - .5:
                stars.append({'x': float(x + .5) / SIZE, 'y': 1 - float(y + .5) / SIZE,
                              'id': str(star['source_id']), 'g': star['phot_g_mean_mag'], 'pm': math.hypot(pmra, pmdec)})
        return {'stars': stars, 'source': 'Gaia DR3; linear proper motion from J2016.0 (no parallax correction).'}
    except Exception:
        raise HTTPException(502, 'Gaia is not responding. SPHEREx playback is still available.')


@app.get('/api/photometry/{key}')
def photometry(key: str, max_frames: int = Query(12, ge=2, le=18)):
    data = read_search(key)
    n = len(data['observations'])
    indices = sorted(set(round(i * (n - 1) / max(1, min(max_frames, n) - 1)) for i in range(min(max_frames, n))))
    results = []
    # Constant angular aperture across FoVs. These are exploratory values, not calibrated photometry.
    scale = data['fov_arcmin'] * 60 / SIZE
    yy, xx = np.indices((SIZE, SIZE))
    radius = np.hypot(xx - (SIZE - 1) / 2, yy - (SIZE - 1) / 2) * scale
    for i in indices:
        try:
            array, row, _, info = image_data(key, i)
            aperture = array[(radius <= 12) & np.isfinite(array)]
            annulus = array[(radius >= 24) & (radius <= 36) & np.isfinite(array)]
            if aperture.size < 3 or annulus.size < 10:
                continue
            proxy = float(np.mean(aperture) - np.median(annulus))
            results.append({'index': i, 'date': row['date'], 'proxy': proxy, 'band': row['band'], 'wavelength_um': info['wavelength_um']})
        except Exception:
            results.append({'index': i, 'error': 'Frame unavailable.'})
    return {'measurements': results, 'warning': 'Exploratory fixed-position brightness proxy. Wavelength, flags, PSF, and source motion can change it; this is not calibrated light-curve photometry.'}


@app.get('/api/resolve')
def resolve(q: str = Query(..., min_length=2, max_length=100)):
    q = q.strip()
    try:
        if re.fullmatch(r'[-+]?\d+(?:\.\d+)?[\s,]+[-+]?\d+(?:\.\d+)?', q):
            ra, dec = map(float, re.split(r'[\s,]+', q))
            if not 0 <= ra < 360 or not -90 <= dec <= 90:
                raise HTTPException(400, 'RA must be 0–359.999° and Dec must be −90–90°.')
        elif re.fullmatch(r'[\d\s:.+\-hmsd,]+', q):
            from astropy.coordinates import SkyCoord
            import astropy.units as u
            coord = SkyCoord(q.replace(',', ' '), unit=(u.hourangle, u.deg))
            ra, dec = float(coord.ra.deg), float(coord.dec.deg)
        else:
            raw = archive.fetch_bytes('https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?' + quote(q, safe=''), timeout=15, max_bytes=1_000_000)
            root = ET.fromstring(raw)
            resolver = next((r for r in root.iter('Resolver') if r.find('jradeg') is not None and r.find('jdedeg') is not None), None)
            if resolver is None:
                raise ValueError('No match')
            ra, dec = float(resolver.findtext('jradeg')), float(resolver.findtext('jdedeg'))
        return {'ra': round(ra, 7), 'dec': round(dec, 7), 'query': q}
    except HTTPException:
        raise
    except archive.ArchiveError:
        raise HTTPException(503, 'Name lookup is unavailable. Enter RA and Dec or choose a suggested target.')
    except Exception:
        raise HTTPException(404, 'Target not found. Try a SIMBAD name or coordinates such as 133.79513, -7.24515.')

ASSETS = {'app.js', 'color-view.js', 'comparison-view.js', 'sky-atlas.js', 'style.css', 'react.production.min.js', 'react-dom.production.min.js', 'htm.js'}

@app.get('/static/{name}')
@app.get('/static/vendor/{name}')
def asset(name: str):
    if name not in ASSETS:
        raise HTTPException(404, 'Not found')
    return FileResponse(ROOT / name, headers={'Cache-Control': 'no-cache'})

@app.get('/')
def home():
    return FileResponse(ROOT / 'index.html', headers={'Cache-Control': 'no-cache'})
