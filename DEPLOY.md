# Deploying "Where To"

Two pieces, two hosts:

- **Frontend** (Next.js) → **Vercel**
- **Backend** (FastAPI, background jobs + SSE) → **Render** (needs a persistent
  process, so it can't run on Vercel's serverless functions)

Deploy the **backend first** — you need its URL to configure the frontend.

---

## 1. Backend on Render

1. Push this repo to GitHub (already at `github.com/Shreyansh303/Where-To`).
2. In the [Render dashboard](https://dashboard.render.com): **New + → Blueprint**,
   pick this repo. Render reads [`render.yaml`](render.yaml) and creates the
   `where-to-backend` web service.
3. When prompted, fill in the secret env vars (blank in the blueprint on purpose):
   - `SERPAPI_API_KEY`
   - `GOOGLE_MAPS_API_KEY`
   - `GROQ_API_KEY`
   - `CORS_ORIGINS` — set after step 2 of the frontend (your Vercel URL). You can
     leave it empty for now and add it once you have the Vercel domain.
   The rest (`GROQ_MODEL`, `CURRENCY`, `FAKE_APIS=0`, `CORS_ORIGIN_REGEX`) come
   from the blueprint.
4. Deploy. When it's live, note the URL, e.g. `https://where-to-backend.onrender.com`.
   Check `https://<that-url>/api/health` → `{"status":"ok","fake_apis":false}`.

Notes
- Build: `pip install .` (deps from `backend/pyproject.toml`). Start:
  `uvicorn app.api.main:app --host 0.0.0.0 --port $PORT`.
- **Free tier sleeps after ~15 min idle**, so the first request after idle takes
  ~30–60s to wake (the frontend just shows the progress screen a bit longer).
  Upgrade the plan if you want it always-on.
- The SQLite cache lives on the instance's ephemeral disk — it repopulates after
  a restart, which is fine (it's only a cache).

---

## 2. Frontend on Vercel

1. In [Vercel](https://vercel.com/new): **Add New → Project**, import the same repo.
2. **Root Directory → `frontend`** (important — the repo is a monorepo). Vercel
   auto-detects Next.js; no build settings to change.
3. Add an environment variable:
   - `NEXT_PUBLIC_API_URL` = your Render backend URL (e.g.
     `https://where-to-backend.onrender.com`) — no trailing slash.
   > This is inlined at **build time**, so if you change it later, redeploy.
4. Deploy. Note your production URL, e.g. `https://where-to.vercel.app`.

---

## 3. Wire CORS back to the backend

1. In Render → the service → **Environment**, set `CORS_ORIGINS` to your Vercel
   production URL (e.g. `https://where-to.vercel.app`) and save (this redeploys).
2. Vercel **preview** deploys get per-build URLs; the blueprint's
   `CORS_ORIGIN_REGEX=https://.*\.vercel\.app` already allows those.

Test: open the Vercel URL, plan a Hong Kong trip, confirm the itinerary streams
in and renders.

---

## Environment variables at a glance

| Where    | Variable                | Value                                            |
|----------|-------------------------|--------------------------------------------------|
| Render   | `SERPAPI_API_KEY`       | your key                                         |
| Render   | `GOOGLE_MAPS_API_KEY`   | your key (Places API New + Routes API enabled)   |
| Render   | `GROQ_API_KEY`          | your key                                          |
| Render   | `CORS_ORIGINS`          | `https://<your-app>.vercel.app`                  |
| Render   | `CORS_ORIGIN_REGEX`     | `https://.*\.vercel\.app` (from blueprint)       |
| Vercel   | `NEXT_PUBLIC_API_URL`   | `https://<your-service>.onrender.com`            |

Secrets never live in the repo — `backend/.env` is gitignored; hosts inject them.
