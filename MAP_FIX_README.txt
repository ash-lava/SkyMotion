SKYMOTION 2.0.1 — FIX FOR "THE SKY MAP COULDN'T CONNECT"

Your /api/health result shows that the previous backend deployed correctly.
The old map message grouped several browser-side failures together; it did
not prove that your browser blocked CDS. This patch corrects that handling.

WHAT TO DO

1. Extract SkyMotion-map-fix.zip.
2. GitHub > your existing repository > the folder containing server.py.
3. Add file > Upload files. Upload ALL files INSIDE the extracted folder.
   Keep them beside the existing server.py. Commit to Render's connected branch.
4. Render > Manual Deploy > Deploy latest commit (or wait for auto-deploy).
5. Hard-refresh the page once the deployment finishes.

No new environment variables, Python packages, or Render commands are needed.
Keep SPHEREX_COLLECTIONS=spherex_dr1 and the existing build/start commands.
New files sky_service.py and sky-atlas.js are required. Upload them too.

CHECK THE UPDATE

Health check should now show version 2.0.1:
https://skymotion-sk2p.onrender.com/api/health

Open the built-in atlas directly:
https://skymotion-sk2p.onrender.com/?atlas=basic

Check the actual image endpoint (a color image should open):
https://skymotion-sk2p.onrender.com/api/sky.jpg?ra=83.82208&dec=-5.39111&fov=1.4&width=800&height=600&survey=dss

If that endpoint returns JSON instead, copy that JSON into the conversation.
It will identify whether both CDS image services failed. If it says Not Found,
the new server version is not deployed yet. If the health check is unavailable,
check the Render deploy log for a missing sky_service.py file.

HOW IT WORKS

Aladin is still used when it loads successfully. If its script, WebAssembly,
or WebGL initialization fails or exceeds 8 seconds, SkyMotion uses a local
image-based atlas. This viewer fetches real DSS/2MASS/WISE images through your
Render server, supports drag/pan, zoom and a coordinate grid, and does not
require an external browser script or WebGL. It tries both documented CDS
HiPS2FITS image servers. After moving, a fresh image replaces the dimmed old
image. It has a maximum 60-degree field, rather than an all-sky projection.

A genuine outage at both CDS image servers can still prevent sky images.
The patch exposes that error clearly instead of attributing it to your browser.
SPHEREx observation search and playback remain independent.

VALIDATION

30 Python tests, 10 React state tests, 10 fallback atlas tests, and 4 map-loader
integration tests passed locally. Three Astropy tests still require the
installed astronomy dependency; the existing Render build command runs them.
Direct live CDS/Render access and browser rendering remain restricted in the
editing workspace, so successful live image retrieval is not claimed here.
