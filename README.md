# FrameFit

FrameFit lets someone upload a photo of themselves, capture one fashion frame, try individual items on that photo, and search for similar products.

Demo mode is the default. It is labeled **Demo data** and uses drawn sample images. It does not pretend those results came from YouCam or Google Lens.

## Local setup

Use two terminals from the repository root.

```bash
cp .env.example .env
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. The dev server proxies `/api` to http://127.0.0.1:8000. Leave `VITE_API_BASE_URL` empty for that setup.

Docker Compose runs the API with a persistent `/data` volume and the Vite dev server:

```bash
cp .env.example .env
docker compose up --build
```

The Compose frontend sets `VITE_API_BASE_URL=http://localhost:8000`, so the browser calls the API directly. `FRONTEND_ORIGINS` must include `http://localhost:5173`.

## Environment

Copy `.env.example`. Provider secrets belong only in the backend environment.

| Variable | Purpose |
| --- | --- |
| `FRAMEFIT_MODE` | `demo`, `mixed`, or `real` |
| `SECRET_KEY` | Signs image URLs |
| `DATABASE_URL` | SQLite URL on a persistent disk |
| `STORAGE_BACKEND` | `local` or `s3` |
| `LOCAL_STORAGE_DIR` | File storage for local mode |
| `S3_*` | S3-compatible bucket for production |
| `FRONTEND_ORIGINS` | Allowed browser origins |
| `PUBLIC_BASE_URL` | Needed only for `YOUCAM_INPUT_MODE=public_url` |
| `YOUCAM_API_KEY` | YouCam bearer token, server-side |
| `YOUCAM_INPUT_MODE` | `file_upload` or `public_url` |
| `YOUCAM_REFERENCE_KIND` | `crop` or `frame` |
| `SERPAPI_API_KEY` | Google Lens key, server-side |
| `YOLO_MODEL` | Default `yolov8s-worldv2.pt` |
| `YOLO_DEVICE` | Default `cpu` |
| `YOLO_CONFIDENCE` | Detector threshold |
| `YOLO_IMAGE_SIZE` | Default `640` |
| `MAX_GENERATIONS_PER_SESSION` | Saved try-on cap. The app asks the user to delete, and does not drop old results. |
| `MAX_STORAGE_BYTES` | Stored-byte cap, same behavior |

`VITE_API_BASE_URL` is the only frontend variable, and it is the API origin. Do not put provider keys in any `VITE_` variable.

### Modes

- **demo:** fixture detection, fixture try-on, fixture product search. Badge: Demo data.
- **mixed:** live YOLOWorld detection when the model loads. Try-on calls the matching YouCam API when `YOUCAM_API_KEY` is set, and stays on fixtures when it is not. A failed live try-on is not replaced with a fixture. Live search only when a SerpApi key is set. The disclosure names each part.
- **real:** live calls only. Missing keys disable those actions. A failed live call is never replaced with a fixture.

## Architecture

The browser stores an opaque workspace token and sends it as `X-Workspace-Token`. The API checks that token on every photo, frame, and job. CORS is not treated as authorization.

A personal photo creates a photo session, an original asset, and a root version. Each successful try-on appends an immutable version whose parent is the version that was active when the job was created. Undo and reset change the active version and do not delete children. A full browser reload selects the original again and keeps history. At most one try-on job runs per photo session. If the person switches version or reloads while it runs, the finished image is still saved under its original parent and does not become the active image.

Detection uses Ultralytics YOLOWorld (`yolov8s-worldv2.pt`) with the class prompts hat, scarf, jacket, coat, shirt, sweater, trousers, skirt, dress, shoe, and bag. Jacket and coat share the Outerwear name, shirt and sweater share Upper body, and trousers and skirt share Lower body. When several boxes share a name, only the highest score is kept. It returns boxes, not masks. The model is loaded once, inference runs in a worker thread, and results are cached by image hash and model settings. People can correct a category, move a box, or draw one.

Try-on calls the YouCam adapters documented in `docs/providers.md`: clothes V4, hat, scarf, and shoes transfer. Product search uploads the item crop to SerpApi and reads Google Lens visual matches. The personal photo is not the search image.

Images are stored on the local disk or in an S3-compatible bucket. Identical bytes in one workspace reuse one asset. Assets are deleted only when no remaining record points at them.

## Deployment

Do not treat a container's writable layer as permanent storage.

### Frontend on Vercel

- Root directory: `frontend`
- Build command: `npm run build`
- Output directory: `dist`
- Environment: `VITE_API_BASE_URL` = the public backend origin, with no trailing path and no secrets

### Backend on Render

Use the `backend` Dockerfile. Start command is already the image command: one Uvicorn worker on `0.0.0.0` and the platform `PORT`.

- Health check: `GET /api/health`
- Readiness: `GET /api/ready` checks that the database answers. Model loading does not block readiness, so a slow weight download does not take the service out of rotation. Detection reports itself unavailable until the model is ready, and manual boxes still work.
- Plan for a CPU instance with enough memory for PyTorch. 4 GB is a safer starting point than a 512 MB web dyno. The first boot downloads `yolov8s-worldv2.pt` into `YOLO_CACHE_DIR`.
- Attach a persistent disk and point `DATABASE_URL` and `LOCAL_STORAGE_DIR` at that disk, or use `STORAGE_BACKEND=s3` for images. SQLite on ephemeral container storage is wiped on redeploy and is unsafe with more than one instance. Run a single instance so the background worker and SQLite are not duplicated.
- Set `FRAMEFIT_MODE=real` only when `YOUCAM_API_KEY` and `SERPAPI_API_KEY` are present. Otherwise the badge must stay honest: use `demo` or `mixed`.
- Keep the service awake during judging if the host sleeps after idle time. A free instance that spins down will miss the first request.

## Tests

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest

cd ../frontend
npm test
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

The browser smoke test starts the API in demo mode and walks upload, two inspiration try-ons, a branch, undo, reset, reload, search, and a product try-on. Separate tests cover local video confirmation and shared-tab capture.

## License and attribution

Application code is under the MIT license in `LICENSE`.

The YOLOWorld weights `yolov8s-worldv2.pt` are provided by Ultralytics and are covered by the [Ultralytics AGPL-3.0 license](https://github.com/ultralytics/assets/blob/main/LICENSE), not by this MIT license. Shipping the model in a hosted service has AGPL obligations that this repository does not waive.

Outfit and Fraunces are used from Google Fonts under the SIL Open Font License.

## Product limits

Trying an item on sends the current photo and the selected reference to YouCam when real mode is on. Product search sends the item crop to SerpApi. The interface says this before a person continues.

Inspiration starts from a dropped, pasted, or uploaded screenshot. To take one from a video, pause it in a browser tab and use Screenshot a browser tab. The browser asks before any pixels are shared, and only the confirmed still is saved.
