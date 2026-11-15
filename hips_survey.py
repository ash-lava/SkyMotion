"""Render small reference maps from the public, live IRSA HiPS survey tiles.

HiPS uses nested HEALPix addressing. In JPEG tiles, the even address bits
select the row and the odd bits select the column (IVOA HiPS 1.0, section 4.2).
Output geometry is local ICRS TAN or wide Hammer-Aitoff, with north up
at the view center and east left.
"""
import io
import math
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

import archive_client as archive

SOURCES = {
    'dss': ('https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color', 9),
    'mass': ('https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color', 9),
    'wise': ('https://irsa.ipac.caltech.edu/data/hips/CDS/AllWISE/RGB-W4-W2-W1', 8),
}
TILE_WIDTH = 512
MAX_TILES = 12
MAX_TILE_CACHE_BYTES = 16_000_000
TILES, TILE_LOCK = OrderedDict(), threading.RLock()
RENDER_LOCK = threading.Lock()  # Bound reprojection memory on small Render instances.
_indices = np.arange(TILE_WIDTH ** 2, dtype=np.uint32)
_compact = np.zeros(TILE_WIDTH ** 2, dtype=np.uint16)
for _bit in range(9):
    _compact |= (((_indices >> (2 * _bit)) & 1) << _bit).astype(np.uint16)
del _indices, _bit


def pixel_addresses(lon, lat, order):
    import astropy.units as u
    from astropy_healpix import HEALPix
    return HEALPix(nside=2 ** (order + 9), order='nested').lonlat_to_healpix(lon * u.deg, lat * u.deg)


def jpeg_positions(addresses):
    local = np.asarray(addresses) & (TILE_WIDTH ** 2 - 1)
    return _compact[local], _compact[local >> 1]


def get_tile(survey, order, index):
    base, maximum = SOURCES[survey]
    if not (0 <= order <= maximum and 0 <= index < 12 * 4 ** order):
        raise archive.ArchiveError('Invalid survey tile address.')
    key = (survey, order, index)
    with TILE_LOCK:
        cached = TILES.get(key)
        if cached and time.monotonic() - cached[0] < 3600:
            TILES.move_to_end(key)
            return cached[1]
    url = f'{base}/Norder{order}/Dir{index // 10000 * 10000}/Npix{index}.jpg'
    raw = archive.fetch_bytes(url, timeout=12, max_bytes=1_500_000, attempts=1)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'JPEG' or image.size != (TILE_WIDTH, TILE_WIDTH):
                raise ValueError('Unexpected survey tile dimensions or format.')
            pixels = np.array(image.convert('RGB'))
    except (OSError, ValueError) as exc:
        raise archive.ArchiveError('IRSA returned an unreadable survey tile.') from exc
    pixels.setflags(write=False)
    with TILE_LOCK:
        TILES[key] = (time.monotonic(), pixels)
        TILES.move_to_end(key)
        while len(TILES) > 24 or sum(item[1].nbytes for item in TILES.values()) > MAX_TILE_CACHE_BYTES:
            TILES.popitem(last=False)
    return pixels


def aitoff_world(x, y, width, height, wcs):
    """Inverse Hammer-Aitoff plus sky rotation, including exact celestial poles."""
    px = -(x - (width - 1) / 2) * abs(wcs.wcs.cdelt[0]) * np.pi / 180
    py = ((height - 1) / 2 - y) * abs(wcs.wcs.cdelt[1]) * np.pi / 180
    valid = px * px / 8 + py * py / 2 <= 1 + 1e-12
    z = np.sqrt(np.maximum(0, 1 - (px / 4) ** 2 - (py / 2) ** 2))
    lon = 2 * np.arctan2(z * px, 2 * (2 * z * z - 1))
    lat = np.arcsin(np.clip(z * py, -1, 1))
    dec0 = np.radians(wcs.wcs.crval[1])
    a, b, c = np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)
    ra = (wcs.wcs.crval[0] + np.degrees(np.arctan2(b, np.cos(dec0) * a - np.sin(dec0) * c))) % 360
    dec = np.degrees(np.arcsin(np.clip(np.sin(dec0) * a + np.cos(dec0) * c, -1, 1)))
    return np.where(valid, ra, np.nan), np.where(valid, dec, np.nan)


def address_grid(wcs, width, height, order):
    # Work in strips: avoid multiple full-size floating-point coordinate grids.
    addresses = np.empty((height, width), dtype=np.int64)
    for start in range(0, height, 64):
        stop = min(start + 64, height)
        yy, xx = np.indices((stop - start, width))
        if wcs.wcs.ctype[0] == 'RA---AIT':
            lon, lat = aitoff_world(xx, yy + start, width, height, wcs)
        else:
            lon, lat = wcs.pixel_to_world_values(xx, height - 1 - (yy + start))
        valid = np.isfinite(lon) & np.isfinite(lat)
        strip = np.full(lon.shape, -1, dtype=np.int64)
        strip[valid] = pixel_addresses(lon[valid], lat[valid], order)
        addresses[start:stop] = strip
    return addresses


def render_survey(spec, survey):
    from astropy.wcs import WCS
    with RENDER_LOCK:
        wcs = WCS(spec)
        width, height = spec['NAXIS1'], spec['NAXIS2']
        # Match the tile resolution to the display without requesting unbounded tiles.
        order = min(SOURCES[survey][1], max(0, math.ceil(math.log2(
            58.6323 / (TILE_WIDTH * abs(spec['CDELT1']))))))
        while True:
            addresses = address_grid(wcs, width, height, order)
            ids = np.unique(addresses[addresses >= 0] >> 18)
            if len(ids) <= MAX_TILES or order == 0:
                break
            order -= 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            tiles = list(pool.map(lambda index: get_tile(survey, order, int(index)), ids))
        output = np.zeros((height, width, 3), dtype=np.uint8)
        regions = addresses >> 18
        for index, tile in zip(ids, tiles):
            mask = regions == index
            rows, columns = jpeg_positions(addresses[mask])
            output[mask] = tile[rows, columns]
        buffer = io.BytesIO()
        Image.fromarray(output).save(buffer, format='JPEG', quality=92)
        return buffer.getvalue()
