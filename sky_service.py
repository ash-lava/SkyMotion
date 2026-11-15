"""Fixed-source CDS HiPS2FITS images for the browser-independent atlas fallback."""
import hashlib
import io
import json
import math
import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from PIL import Image

import archive_client as archive

router = APIRouter()
SURVEYS = {'dss': 'CDS/P/DSS2/color', 'mass': 'CDS/P/2MASS/color', 'wise': 'CDS/P/allWISE/color'}
ENDPOINTS = ('https://alasky.cds.unistra.fr/hips-image-services/hips2fits',
             'https://alaskybis.cds.unistra.fr/hips-image-services/hips2fits')
CACHE, LOCK = OrderedDict(), threading.RLock()
MAX_CACHE_BYTES = 20_000_000


def image_wcs(ra, dec, fov, width, height):
    # fov is the actual angular span of the largest image dimension.
    # TAN intermediate coordinates are degrees, not angles on the sphere.
    scale = math.degrees(2 * math.tan(math.radians(fov) / 2)) / max(width, height)
    return {'NAXIS': 2, 'NAXIS1': width, 'NAXIS2': height, 'WCSAXES': 2,
            'CTYPE1': 'RA---TAN', 'CTYPE2': 'DEC--TAN', 'CUNIT1': 'deg', 'CUNIT2': 'deg',
            'CRVAL1': ra, 'CRVAL2': dec, 'CRPIX1': (width + 1) / 2, 'CRPIX2': (height + 1) / 2,
            'CDELT1': -scale, 'CDELT2': scale}


def fetch_atlas(ra, dec, fov, width, height, survey):
    params = {'hips': SURVEYS[survey], 'width': width, 'height': height, 'format': 'jpg',
              'wcs': json.dumps(image_wcs(ra, dec, fov, width, height), separators=(',', ':'))}
    identity = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    with LOCK:
        entry = CACHE.get(identity)
        if entry and time.monotonic() - entry[0] < 3600:
            CACHE.move_to_end(identity)
            return entry[1]
    errors = []
    for endpoint in ENDPOINTS:
        try:
            raw = archive.fetch_bytes(endpoint, params, timeout=22, max_bytes=5_000_000, attempts=1)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('JPEG', 'PNG') or image.size != (width, height):
                    raise ValueError('Unexpected sky image format or dimensions')
                image.load()
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=92)
                jpeg = output.getvalue()
            with LOCK:
                CACHE[identity] = (time.monotonic(), jpeg)
                CACHE.move_to_end(identity)
                while len(CACHE) > 24 or sum(len(item[1]) for item in CACHE.values()) > MAX_CACHE_BYTES:
                    CACHE.popitem(last=False)
            return jpeg
        except (archive.ArchiveError, ValueError, OSError) as exc:
            errors.append(str(exc))
    raise HTTPException(503, {
        'message': 'Both CDS survey-image services failed. Retry the map shortly; SPHEREx is independent.',
        'code': 'SKY_SURVEY_UNAVAILABLE', 'upstream': errors,
    }, headers={'Retry-After': '30'})


@router.get('/api/sky.jpg')
def sky(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
        fov: float = Query(1.4, ge=.01, le=60), width: int = Query(1024, ge=64, le=1400),
        height: int = Query(768, ge=64, le=1400), survey: str = 'dss'):
    if survey not in SURVEYS:
        raise HTTPException(400, 'Choose dss, mass, or wise.')
    jpeg = fetch_atlas(ra, dec, fov, width, height, survey)
    return Response(jpeg, media_type='image/jpeg', headers={
        'Cache-Control': 'public, max-age=3600', 'X-Sky-Source': SURVEYS[survey],
        'X-Sky-Projection': 'ICRS TAN; north up, east left'})
