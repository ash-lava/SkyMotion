"""IRSA access, deliberately separate from image processing for offline tests."""
import io
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx

SIA_URL = 'https://irsa.ipac.caltech.edu/SIA'
# DR1 is the collection that answered in the reported deployment. QR3 is optional.
SUPPORTED = ('spherex_dr1', 'spherex_dr1_deep', 'spherex_qr3', 'spherex_qr3_deep')
requested = [c.strip() for c in os.getenv('SPHEREX_COLLECTIONS', 'spherex_dr1').split(',') if c.strip()]
COLLECTIONS = tuple(dict.fromkeys(requested)) or ('spherex_dr1',)
if any(c not in SUPPORTED for c in COLLECTIONS):
    raise RuntimeError('SPHEREX_COLLECTIONS must contain documented names: ' + ', '.join(SUPPORTED))

class ArchiveError(Exception):
    pass

def fetch_bytes(url, params=None, *, timeout=35, max_bytes=16_000_000, attempts=2):
    """Retry transient upstream failures, with bounded streamed downloads."""
    for attempt in range(attempts):
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=10), follow_redirects=False,
                              headers={'User-Agent': 'SkyMotion/2.0 (public SPHEREx explorer)'}) as client:
                with client.stream('GET', url, params=params) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ArchiveError('The archive response is too large. Use a smaller field.')
                        chunks.append(chunk)
                    return b''.join(chunks)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise ArchiveError(f'Archive service returned HTTP {status}. Please retry shortly.') from exc
        except httpx.RequestError as exc:
            if attempt == attempts - 1:
                raise ArchiveError('The archive did not respond. Please retry shortly.') from exc
        if attempt < attempts - 1:
            time.sleep(0.5 * (attempt + 1))

def validate_votable(content):
    """A VO service can return HTTP 200 with QUERY_STATUS=ERROR."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ArchiveError('IRSA returned an unreadable table. Please retry shortly.') from exc
    overflow = False
    for item in root.iter():
        if item.tag.rsplit('}', 1)[-1] == 'INFO' and item.get('name', '').upper() == 'QUERY_STATUS':
            status = item.get('value', '').upper()
            if status == 'ERROR':
                raise ArchiveError('IRSA could not complete this collection query. Please retry or check the configured collection.')
            overflow |= status == 'OVERFLOW'
    if not any(e.tag.rsplit('}', 1)[-1] == 'TABLE' for e in root.iter()):
        raise ArchiveError('IRSA returned no result table. Please retry shortly.')
    return overflow

def get_table(ra, dec, radius, collection):
    # Lazy import also lets health/static routes start before any astronomy work.
    from astropy.table import Table
    raw = fetch_bytes(SIA_URL, {'COLLECTION': collection,
        'POS': f'CIRCLE {ra:.8f} {dec:.8f} {radius:.8f}', 'RESPONSEFORMAT': 'votable'})
    overflow = validate_votable(raw)
    try:
        table = Table.read(io.BytesIO(raw), format='votable')
    except Exception as exc:
        raise ArchiveError('IRSA returned a table that could not be read.') from exc
    return table, overflow

def safe_image_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'irsa.ipac.caltech.edu'
            and parsed.port in (None, 443) and parsed.username is None
            and parsed.path.startswith('/ibe/data/spherex/'))

def text_value(row, key, default=''):
    value = row[key] if key in row.keys() else default
    if value is None or str(value) == '--':
        return default
    if isinstance(value, bytes):
        return value.decode('utf-8')
    return str(value)

def number_value(row, key):
    import math
    try:
        value = float(row[key])
        return value if math.isfinite(value) else None
    except (KeyError, ValueError, TypeError):
        return None

def date_from_mjd(value):
    from datetime import datetime, timezone, timedelta
    if value is None:
        return ''
    try:
        return (datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=value)).isoformat().replace('+00:00', 'Z')
    except (ValueError, OverflowError):
        return ''

def search(ra, dec, radius, detector, limit):
    rows, warnings, failed, successful = [], [], {}, []
    with ThreadPoolExecutor(max_workers=min(4, len(COLLECTIONS))) as pool:
        futures = {pool.submit(get_table, ra, dec, radius, c): c for c in COLLECTIONS}
        for future in as_completed(futures):
            collection = futures[future]
            try:
                table, overflow = future.result()
                if overflow:
                    warnings.append(f'{collection}: IRSA truncated this query; this is a partial result.')
                for row in table:
                    band = text_value(row, 'energy_bandpassname')
                    if detector != 'all' and band.upper() != f'SPHEREX-{detector}':
                        continue
                    url = text_value(row, 'access_url')
                    if not safe_image_url(url):
                        continue
                    mjd = number_value(row, 't_min')
                    rows.append({'id': text_value(row, 'obs_id'), 'collection': collection,
                        'band': band, 'mjd': mjd, 'date': date_from_mjd(mjd), 'url': url,
                        'em_min': number_value(row, 'em_min'), 'em_max': number_value(row, 'em_max'),
                        'exptime': number_value(row, 't_exptime')})
                successful.append(collection)
            except Exception as exc:
                reason = str(exc) if isinstance(exc, ArchiveError) else 'The collection could not be read.'
                warnings.append(f'{collection}: {reason}')
                failed[collection] = reason
    if not successful:
        raise ArchiveError('SPHEREx is temporarily unreachable at IRSA. Your sky map still works. Retry the exposure search shortly.')
    # Remove duplicate archive rows; retain independent observations.
    rows = list({r['url']: r for r in rows}.values())
    rows.sort(key=lambda r: (r['mjd'] if r['mjd'] is not None else float('inf'), r['band'], r['id']))
    total = len(rows)
    if total > limit:
        indices = [round(i * (total - 1) / (limit - 1)) for i in range(limit)]
        rows = [rows[i] for i in indices]
    return rows, total, warnings, successful, failed
