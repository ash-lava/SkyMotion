# SkyMotion

A map-first React sky explorer with a black and pale-gold interface, real color survey imagery, and WCS-aligned SPHEREx exposure playback. Start with **START_HERE.txt** for uploading to an existing GitHub repository and redeploying on Render.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. Keep all supplied application files in the same directory. Do not open index.html as a local file. React 18 and htm are included; there is no npm build step. Aladin Lite v3 is attempted first. If its script, WebAssembly, or WebGL initialization fails or takes over 8 seconds, a local image-based atlas takes over. This fallback fetches real survey images through the Python API and needs no external browser script or WebGL. The Python server needs internet access to IRSA, CDS Sesame, and ESA Gaia for their respective features.

## Version 2.0.1 map-loader repair

- Supports both `window.A` and global lexical `A` in classic Aladin bundles.
- Script, initialization, and graphics failures automatically switch to a local atlas.
- `/api/sky.jpg` retrieves a real color survey image using an explicit ICRS TAN WCS. It tries the two documented CDS HiPS2FITS endpoints, validates dimensions and image bytes, and bounds cache memory and request sizes.
- The local atlas supports drag/pan, wheel or pinch zoom, keyboard navigation, survey switching, exact sky-center updates, and a coordinate grid. Images refresh after navigation; this is an image-based fallback, not Aladin's progressive tile renderer. Its largest image dimension is limited to a 60-degree TAN field.
- The browser requests fallback images from the same Render origin. Third-party browser script blocking and WebGL availability no longer determine whether the fallback starts. A real outage at both survey-image services can still prevent imagery.
- Force the local atlas with `?atlas=basic`. The Retry map control retries its image request without reloading the app. Network errors show a specific message; the original Aladin failure is also recorded in the browser console.
- New files `sky_service.py` and `sky-atlas.js` must be uploaded alongside the updated `server.py`, `app.js`, `style.css`, and `index.html`.

## What changed

- Full-screen survey viewer with drag/zoom, real DSS/2MASS/AllWISE color layers, compact target controls, shareable coordinates, responsive phone controls, and a playback dock.
- DR1 is the default SPHEREx collection. Removed speculative probes of historical collection names. `/api/archive` reports the last actual query, not a separate probing process.
- Transient HTTP failures are retried. VO `QUERY_STATUS=ERROR` is detected even when HTTP status is 200. An outage returns 503; a successful empty search returns an empty list. Partial failures retain successful results and are queried again next time.
- FITS `IMAGE`/`SCI` extensions only; never use variance or flags as a science image. Each frame is resampled to a common 192×192 ICRS TAN grid. North is up, east left, and field size is honored instead of applying a fixed 128-pixel crop.
- Frame metadata includes central wavelength where the spectral WCS can be evaluated, coverage, processing version, and any-nonzero-flag fraction. Downloads, memory caches, and metadata cache count are bounded.
- Cancelled requests cannot overwrite a newly selected target. Failed frames stop playback with retry/skip controls. Frames are not browser-cached by mutable observation index.
- Epsilon Indi B's preset now points to the brown-dwarf component. Fast movers use wider cutouts. WISE 0855 uses the challenge's supplied position.
- Gaia DR3 overlay and an explicitly exploratory brightness proxy are retained. Metadata can be downloaded as JSON.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPHEREX_COLLECTIONS` | `spherex_dr1` | Comma-separated documented collection IDs |
| `CACHE_TTL` | `21600` | Search cache duration in seconds |
| `CACHE_DIR` | `cache/` beside server.py | Re-creatable metadata cache |

Supported collection IDs are `spherex_dr1`, `spherex_dr1_deep`, `spherex_qr3`, and `spherex_qr3_deep`. Start with `spherex_dr1`, which answered in the reported deployment. To try weekly quick releases later, set `SPHEREX_COLLECTIONS=spherex_dr1,spherex_qr3`. QR3 is valid; a 502 is a service failure, not proof that the collection is invalid. Earlier QR names are intentionally not defaults.

The cache is disposable. It can disappear on a Render restart. The app needs no database, secrets, or persistent disk for basic operation. Public instances with substantial traffic should add a job queue and rate limiting; FITS work currently runs synchronously and serializes image decoding to bound memory.

## Share a patch

Use Share patch, or construct a URL:

```text
https://YOUR-SITE/?ra=133.7951292&dec=-7.2451472&fov=12&band=D2&layer=wise&mode=sequence
```

`ra` and `dec` use decimal ICRS degrees. `fov` is the SPHEREx cutout width in arcminutes: 1, 2, 3, 6, or 12. `band` selects D1–D6, not a single calibrated spectral channel. `layer` can be `dss`, `mass`, or `wise`. `mode=sequence` loads observations on arrival. Without it, the map opens without querying SPHEREx.

## Science and display limits

- The colorful atlas is a telescope-band composite from a reference survey. It is not SPHEREx time-domain data and not necessarily visible-eye color. No synthetic sky or fake exposure is substituted for missing data.
- The app selects at most 24 observations spread through returned observation times. The timeline slider steps by exposure index, not equal elapsed time. Upstream overflow is reported. Multiple releases can contain reprocessed versions of the same exposure; exact duplicate access URLs are removed, but distinct processing versions are not silently merged.
- Frames are geometrically aligned with bilinear interpolation. This is a quick-look display, not a flux-conserving reduction. Resampling adds no telescope resolution. There is no PSF matching, coaddition, calibrated subtraction, or discovery classifier.
- Each frame is stretched independently at the 5th–99.5th percentile, followed by a square-root stretch. Apparent brightness changes can come from the stretch, wavelength, noise, PSF, contamination, or processing differences.
- The same SPHEREx detector does not mean the same wavelength: its filter varies across the detector. Central wavelength is shown when the product supports it. Flag percentages count any nonzero flag in the displayed covered region; no scientific bit-mask policy is imposed.
- Gaia uses a linear proper-motion approximation from J2016.0, without parallax or perspective acceleration. Missing rings are not evidence of a discovery. Presets are catalog/challenge finding coordinates, not ephemerides. Barnard's Star, Epsilon Indi B, and WISE 0855 default to larger fields to allow for motion.
- The brightness tool uses a fixed 12-arcsecond-radius central aperture and 24–36-arcsecond background annulus on the reprojected image. It reports aperture mean minus annular median, an exploratory surface-brightness proxy; it does not track a moving source, match wavelength, apply PSF corrections, propagate errors, or produce calibrated photometry. Its results are displayed as a table to avoid implying a validated light curve.

## Checks

```bash
python -m unittest -v test_server.py
node test_frontend.cjs
node test_sky_atlas.cjs
node test_map_loader.cjs
```

The Python suite tests archive retry/failure semantics, empty results, detector filtering, chronological sampling, duplicate removal, caching, coordinates, PNG orientation, and static routes. With Astropy installed it also checks an actual VOTable parse, sexagesimal resolution, and rotated-WCS alignment. The React/htm harness tests state, cancellations, playback gating, empty/error states, and shared URLs; it does not test DOM layout or Aladin itself.

At handoff: **30 Python tests passed, 3 Astropy tests skipped, 10 frontend state tests passed, 10 atlas geometry/lifecycle tests passed, 4 map-loader integration tests passed**. Direct outbound requests to the deployed app/IRSA/CDS, package installation, and Chromium rendering were restricted in the editing workspace. Consequently, live FITS downloads, astronomy tests, and visual/browser integration are not claimed as verified. The supplied Render build command runs the full Python suite after dependency installation. Use START_HERE.txt's deployment checks for actual surveys and all five targets.

## Data sources and documentation

- [SPHEREx at IRSA](https://irsa.ipac.caltech.edu/Missions/spherex.html)
- [IRSA introduction: current collections and FITS structure](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)
- [SPHEREx cutout documentation](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html)
- [Cutout tutorial and spectral WCS](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/)
- [CDS HiPS2FITS service documentation and its two endpoints](https://alasky.u-strasbg.fr/hips-image-services/hips2fits)
- [Aladin Lite](https://aladin.cds.unistra.fr/AladinLite/) and [current API reference](https://cds-astro.github.io/aladin-lite/Aladin.html)
- [Epsilon Indi B catalog position](https://simbad.u-strasbg.fr/simbad/sim-id?Ident=Epsilon+Indi+B)
- [RW Aurigae catalog position](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=V%2A+RW+Aur)
- [AAVSO finding coordinates, including R Draconis](https://archive.aavso.org/index.php/aavso-bulletin-coordinates)
- [GitHub upload instructions](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
- [Render deployment instructions](https://render.com/docs/deploys)

## Credits and license

Independent NASA Space Apps project; not an official NASA product. Code: MIT, preserving the supplied LICENSE. React and htm retain their embedded licenses. Aladin Lite is loaded from CDS and is not bundled or relicensed. Survey data retain their source terms and acknowledgments.

SPHEREx data: NASA / JPL / Caltech / IPAC. Reference atlas: DSS / STScI, 2MASS / UMass / IPAC, WISE / NASA / JPL / UCLA. Catalog overlay: ESA Gaia DR3. Viewer and name resolution: CDS Aladin / Sesame.

Publications using SPHEREx data should include the required mission acknowledgment on the linked IRSA mission page.
