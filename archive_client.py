"""IRSA access, deliberately separate from image processing for offline tests."""
import io
import csv
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlencode, quote

import httpx

SIA_URL = 'https://irsa.ipac.caltech.edu/SIA'
TAP_URL = 'https://irsa.ipac.caltech.edu/TAP/sync'
SIA_LIMITS = (16, 4)
SIA_TIMEOUT = 45
SIA_BUDGET = 80
TAP_LIMIT = 16
# Interior detector ranges, in meters: apply BAND before IRSA applies MAXREC.
DETECTOR_BANDS = {
    'D1': '0.0000008 0.0000010', 'D2': '0.0000012 0.0000015',
    'D3': '0.0000017 0.0000023', 'D4': '0.0000026 0.0000036',
    'D5': '0.0000039 0.0000043', 'D6': '0.0000045 0.0000049',
}
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
                              headers={'User-Agent': 'sphere360/2.1 (public SPHEREx explorer)'}) as client:
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

def read_table(raw, required):
    from astropy.table import Table
    overflow = validate_votable(raw)
    try:
        table = Table.read(io.BytesIO(raw), format='votable')
    except Exception as exc:
        raise ArchiveError('IRSA returned a table that could not be read.') from exc
    if not set(required).issubset(table.colnames):
        raise ArchiveError('IRSA returned a table without the required image metadata.')
    return table, overflow

def read_csv_table(raw, required, cap):
    """Parse a bounded CSV response without mistaking HTML/VO errors for empty coverage."""
    if raw.lstrip().startswith(b'<'):
        table, overflow = read_table(raw, required)
    else:
        from astropy.table import Table
        try:
            reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
            names = next(reader, [])
            if not set(required).issubset(names) or len(names) != len(set(names)):
                raise ArchiveError('IRSA returned CSV without the required image metadata.')
            rows = []
            for values in reader:
                if not values:
                    continue
                if len(values) > len(names) and 'cloud_access' in names:
                    # IRSA currently emits unquoted JSON in cloud_access. Its commas
                    # are not additional columns. Repair only that declared field and
                    # validate the JSON before trusting the alignment of the CSV row.
                    index = names.index('cloud_access')
                    extra = len(values) - len(names)
                    cloud = ','.join(values[index:index + extra + 1])
                    if not isinstance(json.loads(cloud), dict):
                        raise ArchiveError('IRSA returned malformed cloud metadata.')
                    values = values[:index] + [cloud] + values[index + extra + 1:]
                if len(values) != len(names):
                    raise ArchiveError('IRSA returned incomplete CSV rows.')
                rows.append(tuple(values))
            table = Table(rows=rows, names=names, dtype=[str] * len(names))
            overflow = False
        except (UnicodeDecodeError, csv.Error, ValueError) as exc:
            raise ArchiveError('IRSA returned an unreadable CSV result.') from exc
    overflow = overflow or len(table) >= cap
    table.meta['query_maxrec'] = cap
    return table, overflow

def read_sia_csv(raw, cap):
    return read_csv_table(raw, ('access_url', 'energy_bandpassname', 't_min'), cap)

def time_constraints(time_range):
    if time_range is None:
        return {}
    import math
    lower, upper = time_range
    if any(v is not None and not math.isfinite(v) for v in (lower, upper)) or (
            lower is not None and upper is not None and lower >= upper):
        raise ArchiveError('Choose a valid, increasing UTC date range.')
    return {'TIME': f"{lower if lower is not None else '-Inf'} {upper if upper is not None else '+Inf'}"}


def within_time(mjd, time_range):
    if time_range is None:
        return True
    lower, upper = time_range
    return mjd is not None and (lower is None or mjd >= lower) and (upper is None or mjd < upper)


def get_table(ra, dec, radius, collection, *, detector='all', time_range=None):
    # Find frames covering the requested center. Field width applies to the FITS cutout.
    # Large/unbounded searches failed at IRSA's proxy in live checks; 16/4-row CSV
    # requests worked. Successful requests took ~21s, so a 15s timeout is insufficient.
    params = {'COLLECTION': collection,
              'POS': f'CIRCLE {float(ra):.12g} {float(dec):.12g} 0.00001',
              'RESPONSEFORMAT': 'CSV', **time_constraints(time_range)}
    if detector != 'all' and detector not in DETECTOR_BANDS:
        raise ArchiveError('Choose a detector from D1 to D6, or all.')
    error = None
    deadline = time.monotonic() + SIA_BUDGET
    for cap in SIA_LIMITS:
        query = {**params, 'MAXREC': cap}
        if detector != 'all':
            query['BAND'] = DETECTOR_BANDS[detector]
        # Preserve the same explicit URI encoding as the successful direct CSV query.
        url = SIA_URL + '?' + urlencode(query, quote_via=quote)
        for attempt in range(1 if cap == SIA_LIMITS[0] else 4):
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                break
            try:
                raw = fetch_bytes(url, timeout=min(SIA_TIMEOUT, remaining),
                                  max_bytes=3_000_000, attempts=1)
                return read_sia_csv(raw, cap)
            except ArchiveError as exc:
                error = exc
                if cap == SIA_LIMITS[-1] and attempt < 3:
                    delay = min(2 ** attempt, max(0, deadline - time.monotonic()))
                    if delay:
                        time.sleep(delay)
    raise ArchiveError(f'IRSA did not complete the bounded live queries. {error}')


def safe_image_url(url):
    try:
        parsed = urlparse(url)
    except (TypeError, ValueError):
        return False
    return (parsed.scheme == 'https' and parsed.netloc in
            ('irsa.ipac.caltech.edu', 'irsa.ipac.caltech.edu:443')
            and re.fullmatch(r'/ibe/data/spherex/[a-z0-9_]+/level2/[A-Za-z0-9_./-]+\.fits', parsed.path)
            and '..' not in parsed.path.split('/') and not parsed.query and not parsed.fragment)


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

def tap_rows(ra, dec, detector, *, time_range=None):
    """IRSA's documented artifact/plane query; it selects images covering the center.

    TAP combines wide/deep products within each requested release family. We report
    that difference instead of pretending it is the same footprint query as SIA.
    """
    band = '' if detector == 'all' else f" AND p.energy_bandpassname = 'SPHEREx-{detector}'"
    families = {c.removesuffix('_deep').removeprefix('spherex_') for c in COLLECTIONS}
    releases = ' OR '.join(f"a.uri LIKE '%/spherex/{release}/level2/%'" for release in sorted(families))
    time_constraints(time_range)
    time_filter = ''
    if time_range is not None:
        lower, upper = time_range
        if lower is not None:
            time_filter += f' AND p.time_bounds_lower >= {lower:.12g}'
        if upper is not None:
            time_filter += f' AND p.time_bounds_lower < {upper:.12g}'
    query = f"""SELECT TOP {TAP_LIMIT} a.uri, p.time_bounds_lower, p.energy_bandpassname
        FROM spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid
        WHERE 1=CONTAINS(POINT('ICRS', {ra:.8f}, {dec:.8f}), p.poly)
        {band} {time_filter} AND ({releases}) ORDER BY p.time_bounds_lower"""
    raw = fetch_bytes(TAP_URL, {'REQUEST': 'doQuery', 'LANG': 'ADQL', 'FORMAT': 'csv',
                               'QUERY': query, 'MAXREC': TAP_LIMIT}, timeout=45, attempts=1)
    table, overflow = read_csv_table(raw, ('uri', 'time_bounds_lower', 'energy_bandpassname'), TAP_LIMIT)
    rows = []
    for item in table:
        uri = text_value(item, 'uri')
        url = uri if uri.startswith('https://') else 'https://irsa.ipac.caltech.edu/' + uri.lstrip('/')
        if not safe_image_url(url):
            continue
        release = urlparse(url).path.split('/')[4]
        bandpass = text_value(item, 'energy_bandpassname')
        if release not in families or (detector != 'all' and bandpass.upper() != f'SPHEREX-{detector}'):
            continue
        mjd = number_value(item, 'time_bounds_lower')
        if not within_time(mjd, time_range):
            continue
        rows.append({'id': urlparse(url).path.rsplit('/', 1)[-1].removesuffix('.fits'),
                     'collection': 'spherex_' + release, 'band': bandpass,
                     'mjd': mjd, 'date': date_from_mjd(mjd), 'url': url,
                     'em_min': None, 'em_max': None, 'exptime': None})
    return rows, overflow

def search(ra, dec, radius, detector, limit, *, diagnostics=None, time_range=None):
    """Return rows and collection outcomes; optionally record the separate TAP outcome."""
    rows, warnings, failed, successful = [], [], {}, []
    outcomes = diagnostics if diagnostics is not None else {}
    time_constraints(time_range)
    options = {'time_range': time_range} if time_range is not None else {}
    outcomes.update(method='SIA2', tap=None, sampling_limited=False, query_limits={})
    with ThreadPoolExecutor(max_workers=min(4, len(COLLECTIONS))) as pool:
        futures = {pool.submit(get_table, ra, dec, radius, c, detector=detector, **options): c for c in COLLECTIONS}
        for future in as_completed(futures):
            collection = futures[future]
            try:
                table, overflow = future.result()
                cap = getattr(table, 'meta', {}).get('query_maxrec')
                if cap is not None:
                    outcomes['query_limits'][collection] = cap
                if overflow:
                    outcomes['sampling_limited'] = True
                    warnings.append(f'{collection}: IRSA returned a limited live sample'
                                    + (f' (up to {cap} records).' if cap else '.'))
                for row in table:
                    band = text_value(row, 'energy_bandpassname')
                    if detector != 'all' and band.upper() != f'SPHEREX-{detector}':
                        continue
                    url = text_value(row, 'access_url')
                    if not safe_image_url(url):
                        continue
                    mjd = number_value(row, 't_min')
                    if not within_time(mjd, time_range):
                        continue
                    rows.append({'id': text_value(row, 'obs_id'), 'collection': collection,
                        'band': band, 'mjd': mjd, 'date': date_from_mjd(mjd), 'url': url,
                        'em_min': number_value(row, 'em_min'), 'em_max': number_value(row, 'em_max'),
                        'exptime': number_value(row, 't_exptime')})
                successful.append(collection)
            except Exception as exc:
                reason = str(exc) if isinstance(exc, ArchiveError) else 'The collection could not be read.'
                warnings.append(f'{collection}: {reason}')
                failed[collection] = reason
    outcomes['unavailable'] = dict(failed)
    if failed:
        try:
            fallback, overflow = tap_rows(ra, dec, detector, **options)
            rows.extend(fallback)
            outcomes.update(method='SIA2 + TAP' if successful else 'TAP', tap={'ok': True, 'error': None})
            warnings.append('IRSA TAP supplied an alternative search covering the field center. '
                            'It combines wide/deep images within the configured release families.')
            if overflow:
                outcomes['sampling_limited'] = True
                warnings.append(f'IRSA TAP returned a limited live sample (up to {TAP_LIMIT} records).')
        except ArchiveError as exc:
            outcomes['tap'] = {'ok': False, 'error': str(exc)}
            warnings.append('The IRSA TAP fallback is also temporarily unavailable.')
    if not successful and not (outcomes['tap'] and outcomes['tap']['ok']):
        raise ArchiveError('IRSA did not complete this live SPHEREx search. '
                           'Please retry shortly or choose a different detector.')
    outcomes['complete_search'] = not failed
    rows = list({r['url']: r for r in rows}.values())
    rows.sort(key=lambda r: (r['mjd'] if r['mjd'] is not None else float('inf'), r['band'], r['id']))
    total = len(rows)
    if total > limit:
        indices = [round(i * (total - 1) / (limit - 1)) for i in range(limit)]
        rows = [rows[i] for i in indices]
    return rows, total, warnings, successful, failed
