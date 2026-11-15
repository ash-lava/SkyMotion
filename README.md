# sphere360

Display real SPHEREx observations from NASA/IPAC IRSA, compare them over time, and explore a separate all-sky reference atlas. The interface uses black, pale gold and white. The existing GitHub repository and Render address keep their original SkyMotion names.

## Version 2.1.0

- UTC date searches and **Add these dates to sequence** extend a limited archive sample with another observing window. Combined sequences keep immutable source identities, chronological order, search provenance and up to 64 frames.
- **Compare two exposures** provides side-by-side images, blinking, a signed difference, and a two-image mean. A and B share contrast limits. Difference and mean require the same detector, verified MJy/sr units and similar spectral-WCS wavelengths. Their masks keep only common finite, wavelength-compatible pixels.
- **Make infrared color** searches live IRSA metadata for three channels. Assign detector exposures to red, green and blue. The closest dates in the returned samples are selected first. Combining dates more than one day apart requires the mixed-date option. Each channel keeps its exact date, wavelength, source URL and display limits.
- Original FITS cutouts, comparison FITS, color PNGs and provenance JSON can be downloaded. Shared URLs preserve observation dates and combined search windows. **About the data → Copy embed code** creates an iframe.
- The five challenge presets have suitable starting fields and detectors; WISE 0855 starts with D6. Live searches and images were checked for all five fields. This does not establish that every target is detected or that its motion/variability is measurable.

Read [START_HERE.txt](START_HERE.txt) to deploy and [HOW_IT_WORKS.txt](HOW_IT_WORKS.txt) for the beginner's guide. `/api/health` reports **2.1.0** after this version is deployed. No new dependency, key or environment variable is required relative to 2.0.7.

## Use the viewer

1. Choose a suggested target, search a name, or enter ICRS RA/Dec in degrees. The atlas accepts any valid coordinates and pans independently of the SPHEREx patch.
2. Choose a 1–12 arcminute SPHEREx cutout and detector D1–D6. Load exposures, then Play or use the arrow keys. Every exposure is aligned to one north-up, east-left sky grid. The timeline gives dates and the actual span of the returned sample.
3. For another observing season, open **Observation dates · UTC**, enter dates and choose **Add these dates to sequence**. Blank boundaries are unbounded; the end date includes the whole UTC day. The main Load button starts a new sequence. Reload these dates starts a fresh search for the currently entered dates.
4. **Compare two exposures** opens a separate comparison. Choose A and B, or use **Find similar wavelength**. It first seeks a match for A with the widest time separation. If A has no match, it looks for another matching pair in the checked sample. Progress, cancellation and unavailable frames are reported.
5. **Make infrared color** opens a three-channel search for the selected field/date window. Find channels, inspect the dates, then Build color image. If a detector search fails, retry or select another detector. Changing the selection clears the previous composite. The color image is a static three-exposure composite, separate from grayscale time playback.

Hatching marks missing science data. **Coverage → At least 95% covered** checks the returned cutouts and limits playback to verified coverage; it does not reject quality-flag bits. The check can take a minute or longer on a cold cache. All frames cancels the check and restores the original sequence.

The colorful **Sky atlas** is a reference map from DSS, 2MASS or AllWISE, not a SPHEREx time series. Drag, scroll, use the coordinate grid, or select All sky. Panning beyond a selected object is unrestricted. **Use this sky position** adopts the map center as the next SPHEREx target.

## What the derived images mean

All science images come from actual IRSA FITS products. No generated sky, saved example, alternate telescope image, or invented pixel replaces a missing exposure.

**Playback:** common 192×192 ICRS TAN grid, bilinear interpolation; independent 5th–99.5th percentile square-root stretch. This can change apparent brightness between frames. It adds no telescope resolution.

**Comparison:** A and B use one shared stretch over their common valid area. The optional median-sky removal subtracts each image's median over that area. It suppresses uniform background changes but does not model structured zodiacal light. Difference is **B − A**: gold is positive, blue negative, gray zero, with a symmetric linear display scale. Mean is **(A + B) / 2**, so moving or variable sources may blur. Missing areas remain missing.

Arithmetic requires matching detector and verified surface-brightness units. The center and every retained arithmetic pixel must differ in wavelength by no more than half the narrower spectral-WCS channel width. This is an approximate bandpass match. There is **no PSF matching, uncertainty propagation or significance calculation**. Residuals are not automatic detections. Flags and processing differences can affect them. FITS exports retain numeric MJy/sr arrays, sky WCS, a VALID mask, source IDs and sky-subtraction settings; JSON retains the source URLs and wavelength rule.

**Infrared color:** real infrared measurements are mapped to visible RGB. These are assigned false colors, not eye-visible or calibrated spectral colors. Each channel uses its own contrast stretch measured on the intersection of all three finite masks. Dates, wavelengths, flags, PSF and channel scaling can create colored features. Mixed-date composites are explicitly labeled and require the option when the span exceeds one day. Saved channel metadata permits the product to be traced back to IRSA. Documentation previews under `docs/` are never runtime fallbacks.

**Flags and saturation:** an any-nonzero flag fraction is reported, not a scientific bad-pixel policy. Some flags describe status; a nonzero value does not by itself mean unusable data. Finite flagged pixels are retained. Saturated or invalid pixels that are non-finite in the science extension remain gaps. Inspect the original FLAGS/VARIANCE products for science use.

The optional brightness tool is a fixed-position, 12-arcsecond-aperture mean-minus-annular-median proxy. It is not a calibrated light curve or spectrum and does not track a moving source. It samples the original sequence independently of playback coverage filtering.

## Archive behavior and limits

SIA2 queries use `COLLECTION`, a small circle around the center, an upstream detector `BAND`, CSV, and `MAXREC=16`, falling back to 4 with bounded retries. Each request allows up to 45 seconds within an 80-second retry scheduling budget per collection. IRSA sometimes returns 502 for one query while another succeeds. HTML/VO error payloads remain errors; they cannot become empty coverage or fabricated frames.

IRSA TAP supplies a bounded alternative if SIA fails. It combines wide/deep images within configured release families and reports that caveat. UTC date constraints are sent upstream and enforced again on returned observation start times. A successful empty search and a failed search have different UI/API states.

A capped response is a **limited live sample, not a complete survey history**. Listings normally cache for six hours. Reload these dates bypasses that cache. Combining up to 20 searches preserves their separate windows and at most 64 frames, spread across returned times if necessary. It cannot recover metadata the archive did not return. Shared combined URLs repeat those live searches; exact returned samples can change. Save metadata to preserve exact product identities.

FITS downloads are limited to validated HTTPS IRSA SPHEREx paths, bounded in size, decoded serially and cached in a bounded memory cache. Only IMAGE/SCI arrays are science data. Primary celestial TAN-SIP WCS is retained; alternate spectral WCS supplies local wavelength/channel width. IMAGE includes zodiacal foreground; it is not automatically subtracted.

New observations in configured collections appear through refreshed live queries. A new release identifier still needs a configuration/code update; release discovery is not automatic. Full 102-channel spectra, matched-PSF subtraction, multi-image weighted coaddition, automatic motion classification and a color time-series mode are not implemented.

## Supplied challenge resources

| Resource | Actual use |
| --- | --- |
| [NASA/IPAC IRSA SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html) | Live SIA2/TAP searches, original FITS science cutouts and archive documentation. |
| [SPHEREx tutorial notebooks](https://caltech-ipac.github.io/irsa-tutorials/spherex/) | Guidance for FITS extensions, cutout access, celestial/spectral WCS, wavelengths, channel widths and processing versions. See the [intro](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/) and [cutout tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/). |
| [Gaia mission resource](https://archive.stsci.edu/missions-and-data/gaia) | Gaia **DR3** catalog overlay; runtime queries go to ESA Gaia's TAP service. Linear proper motion from J2016.0, without parallax/perspective correction. The live Gaia service failed during this release's check; playback and comparison remain independent. |
| [WiseView](http://byw.tools/wiseview) | Supplied viewing reference; no WiseView code, images or API are used. Blinking is a standard astronomical comparison technique. |
| NEOSSat / CADC / CSA tutorials and datasets | Not integrated; the tool's core data are SPHEREx observations. |

Additional sources: the atlas uses NASA/IPAC IRSA's [HiPS registry/mirror](https://irsa.ipac.caltech.edu/data/hips/list) for DSS/STScI, 2MASS/UMass/IPAC and AllWISE/NASA/JPL/UCLA survey tiles. Astropy, Astropy HEALPix, NumPy, SciPy and Pillow support coordinate transformations and rendering. CDS Sesame provides optional name lookup. The built-in atlas replaces the unavailable external Aladin script; Aladin is not a runtime dependency.

## Run and test

```bash
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. Keep the flat application files together. React 18, ReactDOM and htm are vendored; there is no npm build. Render uses Python 3.12.8 and the included `render.yaml`.

```bash
python -m unittest -q test_server.py test_search_dates.py test_comparison.py test_infrared_color.py
node test_frontend.cjs
node test_sky_atlas.cjs
node test_map_loader.cjs
```

Automated checks use isolated test fixtures; the application never loads them as observations. Live results, browser checks and scientific limits are recorded in [VALIDATION.txt](VALIDATION.txt) and [docs/CHALLENGE_COVERAGE.md](docs/CHALLENGE_COVERAGE.md).

| Setting | Default |
| --- | --- |
| `SPHEREX_COLLECTIONS` | `spherex_dr1` |
| `CACHE_TTL` | `21600` seconds |
| `CACHE_DIR` | `cache/` beside server.py |

Supported collections: `spherex_dr1`, `spherex_dr1_deep`, `spherex_qr3`, `spherex_qr3_deep`. Keep DR1 as the starting configuration. The app needs internet access to IRSA, plus CDS Sesame/ESA Gaia for those optional features. Caches are disposable; no database or API secret is required. High-traffic public deployments need a job queue/rate limiting beyond the current bounded, synchronous processing.

## URLs and embedding

```text
https://skymotion-sk2p.onrender.com/?ra=133.7951292&dec=-7.2451472&fov=12&band=D6&mode=sequence
```

Coordinates are ICRS degrees; SPHEREx `fov` is arcminutes. `start`/`end` are UTC `YYYY-MM-DD` dates. `windows` is a JSON array of start/end date objects for combined live searches; Share view constructs it. Atlas links use `mode=atlas`, `layer=dss|mass|wise`, and independent `atlas_ra`, `atlas_dec`, `atlas_fov`. Atlas zoom ranges from 0.01 to 360 degrees; views wider than 60 use Hammer-Aitoff, with 360 fitting the full sphere. Smaller fields use TAN. Atlas sampling is for reference display, not a flux-conserving reduction.

Copy embed code from About the data, then paste the iframe into a site that permits external embeds. The existing Render address continues to work after the rename. The host site's own content-security policy can restrict embeds.

## Credits and license

Independent NASA Space Apps project, not an official NASA product. NASA does not endorse this project. MIT code license; the supplied LICENSE and vendored library licenses are preserved. Data retain their original source terms.

SPHEREx: NASA / JPL / Caltech / IPAC. Gaia: ESA Gaia. Atlas surveys: DSS / STScI, 2MASS / UMass / IPAC, WISE / NASA / JPL / UCLA; HiPS generation by CDS, hosting by NASA/IPAC IRSA. Name resolution: CDS Sesame. Publications using SPHEREx data should include the mission's required acknowledgment on the linked IRSA mission page.
