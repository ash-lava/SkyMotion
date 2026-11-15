"""Reference atlas images rendered from the public IRSA HiPS survey mirror."""
import hashlib
import json
import math
import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import archive_client as archive
import hips_survey

router = APIRouter()
SURVEYS = {'dss': 'CDS/P/DSS2/color', 'mass': 'CDS/P/2MASS/color', 'wise': 'CDS/P/allWISE/color'}
CACHE, LOCK = OrderedDict(), threading.RLock()
MAX_CACHE_BYTES = 20_000_000


def image_wcs(ra, dec, fov, width, height):
    # For TAN, fov is the angular span of the largest dimension.
    # Wider AIT values set overview zoom; 360 fits the whole sphere.
    projection = 'TAN' if fov <= 60 else 'AIT'
    if projection == 'TAN':
        scale = math.degrees(2 * math.tan(math.radians(fov) / 2)) / max(width, height)
    else:
        # Hammer-Aitoff fits the whole sphere into an ellipse at zoom width 360.
        fit = min(width / (4 * math.sqrt(2)), height / (2 * math.sqrt(2)))
        scale = math.degrees(fov / 360 / fit)
    spec = {'NAXIS': 2, 'NAXIS1': width, 'NAXIS2': height, 'WCSAXES': 2,
            'CTYPE1': 'RA---' + projection, 'CTYPE2': 'DEC--' + projection, 'CUNIT1': 'deg', 'CUNIT2': 'deg',
            'CRVAL1': ra, 'CRVAL2': dec, 'CRPIX1': (width + 1) / 2, 'CRPIX2': (height + 1) / 2,
            'CDELT1': -scale, 'CDELT2': scale}
    if projection == 'TAN':
        spec['LONPOLE'] = 180.0
    return spec


def fetch_atlas(ra, dec, fov, width, height, survey):
    spec = image_wcs(ra, dec, fov, width, height)
    params = {'survey': survey, 'wcs': spec}
    identity = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    with LOCK:
        entry = CACHE.get(identity)
        if entry and time.monotonic() - entry[0] < 3600:
            CACHE.move_to_end(identity)
            return entry[1]
    try:
        jpeg = hips_survey.render_survey(spec, survey)
    except (archive.ArchiveError, ValueError, OSError) as exc:
        raise HTTPException(503, {
            'message': 'The IRSA reference-survey images could not be loaded. Retry the atlas shortly. '
                       'SPHEREx exposure search is separate.',
            'code': 'SKY_SURVEY_UNAVAILABLE', 'upstream': [str(exc)],
        }, headers={'Retry-After': '30'}) from exc
    with LOCK:
        CACHE[identity] = (time.monotonic(), jpeg)
        CACHE.move_to_end(identity)
        while len(CACHE) > 24 or sum(len(item[1]) for item in CACHE.values()) > MAX_CACHE_BYTES:
            CACHE.popitem(last=False)
    return jpeg


@router.get('/api/sky.jpg')
def sky(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
        fov: float = Query(6, ge=.01, le=360), width: int = Query(1024, ge=64, le=1400),
        height: int = Query(768, ge=64, le=1400), survey: str = 'dss'):
    if survey not in SURVEYS:
        raise HTTPException(400, 'Choose dss, mass, or wise.')
    jpeg = fetch_atlas(ra, dec, fov, width, height, survey)
    return Response(jpeg, media_type='image/jpeg', headers={
        'Cache-Control': 'public, max-age=3600', 'X-Sky-Source': SURVEYS[survey],
        'X-Sky-Provider': 'NASA/IPAC IRSA HiPS mirror',
        'X-Sky-Projection': 'ICRS TAN; north up, east left' if fov <= 60 else 'ICRS AIT; north up at center, east left'})
