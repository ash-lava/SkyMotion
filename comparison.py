"""Quick-look arithmetic on aligned, measured SPHEREx science pixels only."""
import io
import math

import numpy as np
from PIL import Image


def exposure_metadata(row, info, index):
    return {'source_index': index, **{k: row.get(k) for k in ('id', 'date', 'mjd', 'band', 'collection')},
            'archive_url': row.get('url'),
            **{k: info.get(k) for k in ('wavelength_um', 'bandwidth_um', 'unit', 'version', 'flagged_fraction')}}


def wavelength_match(first, second):
    values = [first.get('wavelength_um'), second.get('wavelength_um'),
              first.get('bandwidth_um'), second.get('bandwidth_um')]
    if not all(isinstance(v, (float, int)) and math.isfinite(v) and v > 0 for v in values):
        return False
    a, b, wa, wb = values
    return abs(a - b) <= .5 * min(wa, wb)


def prepare(first, second, a, b, *, background=True):
    """Use common coverage and, for arithmetic, local spectral-WCS agreement.

    Half the narrower channel width is a conservative quick-look tolerance, not
    identical filter transmission, PSF matching or calibrated difference imaging.
    No source fitting, interpolation across gaps, or quality-bit policy is applied.
    """
    if a == b:
        raise ValueError('Choose two different exposures.')
    aa, ar, grid, ai = first
    bb, br, _, bi = second
    if aa.shape != bb.shape:
        raise ValueError('The two images do not share a sky grid.')
    overlap = np.isfinite(aa) & np.isfinite(bb)
    if overlap.sum() < 20:
        raise ValueError('These exposures have too little common coverage. Choose another pair or a smaller cutout.')
    reasons = []
    if not ar.get('band') or ar.get('band') != br.get('band'):
        reasons.append('The exposures use different detectors.')
    if ai.get('unit') != 'MJy/sr' or bi.get('unit') != 'MJy/sr':
        reasons.append('Compatible surface-brightness units could not be verified.')
    if not wavelength_match(ai, bi):
        reasons.append('Center wavelengths are unknown or differ by more than half the narrower channel width.')
    matched = overlap.copy()
    maps = [ai.get('_wavelength_map'), bi.get('_wavelength_map'),
            ai.get('_bandwidth_map'), bi.get('_bandwidth_map')]
    if all(isinstance(v, np.ndarray) and v.shape == aa.shape for v in maps):
        aw, bw, ad, bd = maps
        matched &= np.isfinite(aw) & np.isfinite(bw) & np.isfinite(ad) & np.isfinite(bd)
        matched &= (aw > 0) & (bw > 0) & (ad > 0) & (bd > 0) & (np.abs(aw - bw) <= .5 * np.minimum(ad, bd))
        if matched.sum() < 20:
            reasons.append('Too few common pixels meet the local wavelength tolerance.')
    else:
        matched[:] = False
        reasons.append('Per-pixel wavelengths and channel widths could not be verified.')
    arithmetic = not reasons
    mask = matched if arithmetic else overlap
    av, bv = np.asarray(aa, dtype=np.float32).copy(), np.asarray(bb, dtype=np.float32).copy()
    am = float(np.median(av[mask])) if background else 0.
    bm = float(np.median(bv[mask])) if background else 0.
    av -= am
    bv -= bm
    av[~mask] = np.nan
    bv[~mask] = np.nan
    low, high = np.percentile(np.concatenate((av[mask], bv[mask])), [5, 99.5])
    high = max(float(high), float(low) + 1e-8)
    difference = np.where(mask, bv - av, np.nan)
    mean = np.where(mask, (av + bv) * .5, np.nan)
    difference_limit = max(float(np.percentile(np.abs(difference[mask]), 99.5)), 1e-8)
    warnings = ['Quick-look comparison: no PSF matching, uncertainty propagation or significance test. '
                'Small wavelength differences, noise, flags and processing changes can leave residuals.',
                'Quality-flagged pixels are retained. Inspect the flag fractions and original FITS flags.']
    if background:
        warnings.append('Each image has its median over the displayed common area removed. '
                        'This suppresses uniform sky changes; it does not remove structured zodiacal light.')
    if ai.get('version') != bi.get('version'):
        warnings.append('These exposures have different processing versions.')
    if not arithmetic:
        warnings.append('A and B can be inspected, but difference and mean are disabled until wavelength and unit checks pass.')
    times = [ar.get('mjd'), br.get('mjd')]
    elapsed = abs(times[1] - times[0]) if all(v is not None for v in times) else None
    metadata = {
        'a': exposure_metadata(ar, ai, a), 'b': exposure_metadata(br, bi, b),
        'time_separation_days': elapsed, 'arithmetic_available': arithmetic, 'reasons': reasons,
        'common_coverage': float(overlap.mean()), 'wavelength_matched_coverage': float(matched.mean()),
        'displayed_coverage': float(mask.mean()), 'background_removed': background,
        'background_a': am, 'background_b': bm, 'unit': 'MJy/sr' if ai.get('unit') == bi.get('unit') == 'MJy/sr' else None,
        'shared_limits': [float(low), high], 'difference_limits': [-difference_limit, difference_limit],
        'wavelength_rule': 'Same detector; center and each arithmetic pixel within half the narrower spectral-WCS channel width.',
        'stretch': 'A, B and mean: shared 5–99.5 percentile square-root stretch. Difference: linear, symmetric 99.5 percentile of absolute residual.',
        'difference_definition': 'B minus A', 'mean_definition': '(A + B) / 2; moving or variable sources may blur.',
        'mask_definition': 'Intersection of finite science coverage. Arithmetic also requires local wavelength agreement; all other pixels remain missing.',
        'warnings': warnings,
    }
    return {'a': av, 'b': bv, 'difference': difference, 'mean': mean,
            'mask': mask, 'metadata': metadata, 'grid': grid}


def png(comparison, view):
    if view not in ('a', 'b', 'difference', 'mean'):
        raise ValueError('Choose A, B, difference or mean.')
    metadata = comparison['metadata']
    if view in ('difference', 'mean') and not metadata['arithmetic_available']:
        raise ValueError(' '.join(metadata['reasons']))
    mask = comparison['mask']
    array = np.where(mask, comparison[view], 0.)
    if view == 'difference':
        # Gold: B brighter. Blue: A brighter. Neutral gray is zero residual.
        values = np.clip(array / metadata['difference_limits'][1], -1, 1)
        color = np.array([32., 32., 32.]) + np.maximum(values[..., None], 0) * np.array([211., 184., 107.])
        color += np.maximum(-values[..., None], 0) * np.array([78., 151., 206.])
    else:
        low, high = metadata['shared_limits']
        gray = np.sqrt(np.clip((array - low) / (high - low), 0, 1)) * 255
        color = np.repeat(gray[..., None], 3, axis=-1)
    rgba = np.concatenate((color.astype(np.uint8), (mask.astype(np.uint8) * 255)[..., None]), axis=-1)
    buffer = io.BytesIO()
    Image.fromarray(np.flipud(rgba)).save(buffer, format='PNG')
    return buffer.getvalue()
