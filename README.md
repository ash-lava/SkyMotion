# SkyMotion

A React sky explorer with a black and pale-gold interface, live IRSA searches, and WCS-aligned SPHEREx exposure playback. Start with **START_HERE.txt** to update the existing Render service.

## Version 2.0.7: plain interface wording

The interface uses direct labels and instructions. The sidebar reads “Find a target” and “Search by name or enter coordinates.” Promotional taglines were removed from the header, introduction, loading screen, empty state and About dialog. Source credits, coverage explanations and scientific limits remain available. See `docs/COPY_REFERENCES.txt` for the published astronomy-site copy used as reference.

After deployment, `/api/health` should report **2.0.7**. No new package or setting is required.

## Missing data and coverage (introduced in 2.0.6)

Missing SPHEREx science pixels are transparent and show a hatched background, with a coverage percentage and legend. Valid dark pixels remain opaque. No pixels are filled from another exposure or the reference atlas.

The timeline's **Coverage** selector defaults to **All frames**. Choose **At least 95% covered** to check the loaded cutouts and restrict playback to verified frames meeting that threshold. The first check downloads science cutouts and can take a minute or longer; progress is shown, playback pauses, and selecting All frames cancels the check. Unverified frames are excluded from this filtered view and counted separately. All frames remain available. Coverage measures finite science pixels, independently of quality flags.

Filtered navigation retains the original exposure identifiers. Metadata export retains every returned observation, measured coverage where known, displayed source indices and the active threshold. No new dependency or setting is needed; `/api/health` should report **2.0.7** after deployment.

## Free sky navigation (introduced in 2.0.5)

Pan beyond the selected object, enter any valid RA/Dec, and zoom out to a complete all-sky overview. The atlas has its own center and zoom, independent of the selected SPHEREx patch. Changing a target keeps your map zoom; switching views or sharing a link preserves the panned location and zoom.

The **All sky** control fits the complete sphere into the viewport. Coordinate entry opens in atlas mode; suggested places remain available in a collapsible list. A marker identifies the selected SPHEREx patch without bounding the map. **Use this sky position** selects the current map center for a later exposure search while preserving the surrounding view.

No dependency or environment change is needed relative to 2.0.4. After deployment, `/api/health` should report **2.0.7**.

## Sky atlas

The atlas now displays real DSS, 2MASS and AllWISE imagery from NASA/IPAC IRSA's public HiPS mirror. It uses the built-in map directly, with no external Aladin script or WebGL requirement. The previous CDS script/image addresses returned 404 or connection failures in the deployed service.

`hips_survey.py` selects the needed survey tiles, projects them onto the requested ICRS view, with north up at its center and east left and returns a JPEG through `/api/sky.jpg`. Dragging, zooming, survey selection and the coordinate grid remain available. Tile count, downloads, cached bytes and simultaneous reprojection are bounded. This is a reference map built from real survey data; it is separate from SPHEREx exposure playback.

Render installs one new dependency, `astropy-healpix`, from `requirements.txt` during the normal build. No new API key or environment variable is required. After deployment, `/api/health` should report **2.0.7**. Read **HOW_IT_WORKS.txt** for a beginner's explanation of the browser, server, data sources, deployment and error messages.

## SPHEREx live search (introduced in 2.0.3)

The supplied M101 CSV contains four valid IRSA exposure records. Live checks also found that small queries could succeed while larger queries failed at the proxy, and successful searches took about 21 seconds. This corrects the earlier diagnosis that treated the failures as a general archive outage.

- Search requests use CSV, a small circle around the requested center, and `MAXREC=16`, falling back to 4 records with bounded retries. A selected detector is sent as an upstream `BAND` filter before the row limit, so unrelated detector rows cannot exhaust the small response first.
- SIA requests allow up to 45 seconds each, within an 80-second retry scheduling budget per collection. The previous 15-second timeout was shorter than the successful live responses. If SIA fails, the existing IRSA TAP alternative uses a detector/release-filtered query limited to 16 records.
- The CSV parser handles IRSA's unquoted JSON `cloud_access` field and checks required columns and row alignment. HTML proxy pages, malformed rows, and VO errors remain failures; they cannot masquerade as empty coverage.
- A bounded result is a **limited live sample**, not the full survey history. The API exposes `sampling_limited`, `total_lower_bound`, `query_limits`, and `queried_at`; the UI shows lower-bound counts and an explicit notice. Refresh archive bypasses the search cache.
- The home page starts a live M101 search. All five challenge targets, arbitrary coordinates, detector selection, and cutout sizing remain available. Exact UTC exposure times distinguish frames taken on the same day.
- The reference sky atlas opens on request. It uses IRSA HiPS tiles and is not initialized during SPHEREx playback. Its image requests are separate from the SIA/TAP exposure searches.
- The earlier TAP recovery, immutable artifact-sequence keys, HTTPS science-product restrictions, partial-failure handling, and metadata provenance remain in place. Both search methods now find exposures covering the field center; cutout size controls the displayed field. TAP combines wide/deep products within configured release families and reports that caveat.

Runtime searches and FITS downloads use IRSA. No bundled observation listing, saved M101 sequence, AWS mosaic, synthetic sky, or offline fallback is served. The uploaded CSV is included only under `tests/fixtures/` for parser regression tests.

Keep `SPHEREX_COLLECTIONS=spherex_dr1` for the SPHEREx release selection.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. Keep all application files together. React 18 and htm are included, with no npm build step. The server needs internet access to IRSA for the atlas and SPHEREx, CDS Sesame for optional name lookup, and ESA Gaia for the optional catalog overlay.

## Atlas behavior

The built-in atlas supports drag/pan, wheel or pinch zoom, keyboard navigation, survey switching, exact sky-center updates and a coordinate grid. It fetches a new projected image after navigation. It does not progressively stream high-resolution tiles in the browser. Close views up to a 60-degree field use TAN projection. Wider views use Hammer-Aitoff; zoom width 360 fits the whole sky into the viewport, including on portrait phones. The outside of the projected ellipse is blank. Both `?mode=atlas` and the older `?atlas=basic` open the atlas directly.

The renderer uses equatorial HiPS JPEG tiles and nearest-pixel sampling via Astropy HEALPix onto a TAN or Hammer-Aitoff grid. It is a reference display, not a flux-conserving scientific reduction. It requests at most 12 tiles per view, reducing resolution if needed, with at most four tile downloads and one reprojection at a time. Tile images must be 512 by 512 JPEGs from fixed IRSA survey paths. The byte-bounded tile and map caches expire after one hour. Missing or unreadable tiles produce an explicit error and Retry map control.

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

Use Share view, or construct a URL:

```text
https://YOUR-SITE/?ra=133.7951292&dec=-7.2451472&fov=12&band=D2&layer=wise&mode=sequence
```

`ra` and `dec` use decimal ICRS degrees. `fov` is the SPHEREx cutout width in arcminutes: 1, 2, 3, 6, or 12. `band` selects D1–D6, not a single calibrated spectral channel. `layer` can be `dss`, `mass`, or `wise`. `mode=sequence` loads observations on arrival. Shared coordinate URLs without it open the atlas. The bare home URL starts a live M101 sequence; `?mode=atlas` or `?atlas=basic` opens the optional atlas without an exposure search.

Atlas links also include `atlas_ra`, `atlas_dec`, and `atlas_fov`. These preserve the map view independently of the selected SPHEREx coordinates. `atlas_fov` ranges from 0.01 to 360: up to 60 it is the largest TAN field dimension in degrees; above 60 it controls Hammer-Aitoff zoom, with 360 showing the whole sphere. It does not enlarge the SPHEREx cutout. A direct arbitrary-position atlas URL can use `?mode=atlas&ra=12.345&dec=-45.67`; the atlas defaults to a 6-degree surrounding field.

## Science and display limits

- The colorful atlas is a telescope-band composite from a reference survey. It is not SPHEREx time-domain data and not necessarily visible-eye color. No synthetic sky or fake exposure is substituted for missing data.
- Each configured collection returns at most 16 records, or 4 after a smaller-query retry. TAP returns at most 16 records across release families. This can miss long time baselines or later observations; IRSA response order is not a complete survey inventory. When more than 24 records are returned across collections, the app selects at most 24 observations spread through those returned times. The timeline slider steps by exposure index, not equal elapsed time. Upstream overflow is reported. Multiple releases can contain reprocessed versions of the same exposure; exact duplicate access URLs are removed, but distinct processing versions are not silently merged.
- Frames are geometrically aligned with bilinear interpolation. This is a quick-look display, not a flux-conserving reduction. Resampling adds no telescope resolution. There is no PSF matching, coaddition, calibrated subtraction, or discovery classifier.
- Each frame is stretched independently at the 5th–99.5th percentile, followed by a square-root stretch. Apparent brightness changes can come from the stretch, wavelength, noise, PSF, contamination, or processing differences.
- The same SPHEREx detector does not mean the same wavelength: its filter varies across the detector. Central wavelength is shown when the product supports it. Flag percentages count any nonzero flag in the displayed covered region; no scientific bit-mask policy is imposed.
- Gaia uses a linear proper-motion approximation from J2016.0, without parallax or perspective acceleration. Missing rings are not evidence of a discovery. Presets are catalog/challenge finding coordinates, not ephemerides. Barnard's Star, Epsilon Indi B, and WISE 0855 default to larger fields to allow for motion.
- The brightness tool uses a fixed 12-arcsecond-radius central aperture and 24–36-arcsecond background annulus on the reprojected image. It reports aperture mean minus annular median, an exploratory surface-brightness proxy; it does not track a moving source, match wavelength, apply PSF corrections, propagate errors, or produce calibrated photometry. Its results are displayed as a table to avoid implying a validated light curve.

## Infrared color feasibility example

SPHEREx can produce false-color composites from real infrared wavelengths. [This generated M101 example](docs/spherex-color-preview.png) assigns D6 (4.851 µm) to red, D3 (2.196 µm) to green and D1 (0.991 µm) to blue. Its [source provenance](docs/spherex-color-provenance.json) records the live IRSA products, wavelengths and valid coverage. These observations are from **9 and 22 May 2025**. This is a labeled static feasibility example, not simultaneous color or a color-playback feature.

The three FITS science arrays are aligned on a common grid. Only pixels valid in all three channels are shown; each channel uses the existing 5–99.5 percentile square-root stretch. Colors are qualitative; observation-time differences, flags, noise, PSF and processing differences can create colored features. Color playback would need suitable wavelength/date groups and explicit provenance.

Regenerate the example from the documented public IRSA cutouts with `python tools/make_color_example.py --output-dir /tmp/skymotion-color`. It is a documentation utility; the web application does not load the saved example as sky data.

## Checks

```bash
python -m unittest -v test_server.py
node test_frontend.cjs
node test_sky_atlas.cjs
node test_map_loader.cjs
```

The Python suite tests archive retry/failure semantics, empty results, detector filtering, chronological sampling, duplicate removal, caching, coordinates, PNG orientation, and static routes. With Astropy installed it also checks an actual VOTable parse, sexagesimal resolution, and rotated-WCS alignment. The React/htm harness tests state, cancellations, playback gating, empty/error states, and shared URLs; it does not test browser layout.

Validation of version 2.0.6: **65 Python tests, 26 frontend state tests, 15 atlas geometry/lifecycle tests, and 5 map lifecycle integration tests passed.** Five unmocked browser checks verify the actual partially covered M101 exposure, mask counts, coverage filtering, stable frame indices, export and responsive layout. Earlier free-map and live-search regressions remain covered. Browser and live-service verification is recorded in `VALIDATION.txt`. Regression checks use isolated fixtures and do not substitute simulated observations into the application.

## Data sources and documentation

- [SPHEREx at IRSA](https://irsa.ipac.caltech.edu/Missions/spherex.html)
- [IRSA introduction: current collections and FITS structure](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)
- [SPHEREx cutout documentation](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html)
- [Cutout tutorial and spectral WCS](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/)
- [IRSA survey mirror registry](https://irsa.ipac.caltech.edu/data/hips/list)
- [IVOA HiPS image standard](https://www.ivoa.net/documents/HiPS/20170519/REC-HIPS-1.0-20170519.pdf)
- [Astropy HEALPix](https://astropy-healpix.readthedocs.io/)
- [Epsilon Indi B catalog position](https://simbad.u-strasbg.fr/simbad/sim-id?Ident=Epsilon+Indi+B)
- [RW Aurigae catalog position](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=V%2A+RW+Aur)
- [AAVSO finding coordinates, including R Draconis](https://archive.aavso.org/index.php/aavso-bulletin-coordinates)
- [GitHub upload instructions](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
- [Render deployment instructions](https://render.com/docs/deploys)

## Credits and license

Independent NASA Space Apps project; not an official NASA product. Code: MIT, preserving the supplied LICENSE. React and htm retain their licenses; see THIRD_PARTY_LICENSES.txt. Survey data retain their source terms and acknowledgments.

SPHEREx data: NASA / JPL / Caltech / IPAC. Reference atlas: DSS / STScI, 2MASS / UMass / IPAC, WISE / NASA / JPL / UCLA. Catalog overlay: ESA Gaia DR3. HiPS survey generation: CDS. Survey hosting: NASA/IPAC IRSA. Name resolution: CDS Sesame.

Publications using SPHEREx data should include the required mission acknowledgment on the linked IRSA mission page.
