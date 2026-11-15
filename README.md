# SkyMotion

React front end (no build step, files in `static/`, React and htm vendored) served by the FastAPI backend in `server.py`.

**Free deploy (Render, no Docker):** put these files in a GitHub repo, then Render > New > Blueprint > pick the repo. Uses `render.yaml`.


# SkyMotion — real SPHEREx explorer

A web UI and Python API that query the NASA/IPAC IRSA SIA2 archive for real SPHEREx DR1 and QR3 spectral-image observations. It requests small FITS cutouts, renders image frames, and offers a **non-calibrated** brightness proxy (not scientifically validated light curves).

## Run

```bash
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 . Requires internet access to IRSA. Initial archive requests and image cutouts may be slow. `cache/` is created automatically. Host on a Python-compatible service (Render, Railway, etc.), **not static-only hosting**. Do not open `index.html` directly: the API requires the Python server.

**Deploy on Hugging Face (needs a Docker or Gradio Space):** create a Hugging Face Space with SDK = Docker, then drag all files of this folder into its Files tab. The front matter above sets the port.

**Deploy (GitHub):** push this folder to GitHub, then on Render choose New > Blueprint (it reads `render.yaml`). Railway/Fly work with the included `Dockerfile`.

Collections are probed live (`/api/archive`); only those IRSA answers are searched.

## Notes and limitations

- The server searches two SIA2 collections (`spherex_dr1`, `spherex_qr3`) and fetches individual real FITS cutouts. It does not generate mosaics or align images onto a common pixel grid. Each cutout is independently stretched, so apparent changes may be instrumental.
- Detector selection is **not** a selection of one of 102 calibrated spectral channels. SPHEREx uses a spatially varying linear variable filter.
- The brightness proxy measures a fixed aperture near the image center with annulus background subtraction. It is **not** calibrated flux, does not propagate errors, does not correct source motion or variable wavelength, and should not be used to make discovery claims.
- External archive connectivity, data availability, and FITS cutout compatibility vary. Errors are displayed rather than replaced with fake data.
- A production deployment needs async job queues, bounded cache eviction, rate limits, more careful WCS reprojected cutouts, quality flags, validated photometry, and persistent object tracking.

Data documentation: https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/

SPHEREx is a joint project of JPL and Caltech funded by NASA. This is an independent project.

## Live-data additions
- **Target resolver** (`/api/resolve`): SIMBAD/NED names via CDS, decimal degrees, or sexagesimal.
- **Gaia DR3 overlay** (`/api/overlay`): queries ESA's Gaia TAP and moves each star from J2016.0 to the exposure date using its proper motion, then projects it through that frame's WCS. A moving object with no ring is a candidate.
- **New releases**: set `SPHEREX_COLLECTIONS=spherex_dr1,spherex_qr3,<new>` (comma-separated). Search cache lifetime is `CACHE_TTL` seconds (default 21600).

## License

Code: MIT (see `LICENSE`). Data and services keep their own terms: NASA/IPAC IRSA (SPHEREx), ESA Gaia DR3, CDS SIMBAD. This is an independent project, not an official NASA product.
