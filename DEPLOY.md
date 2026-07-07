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
   The rest (`GROQ_MODEL`, `CURRENCY`, `FAKE_APIS=0`, `CORS_ORIGIN_REGEX`) come
   from the blueprint. **You don't need to set `CORS_ORIGINS`** — the
   `CORS_ORIGIN_REGEX` already allows every `*.vercel.app` origin (see step 3).
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

## 3. CORS

Nothing to do if your frontend is on a `*.vercel.app` domain — the blueprint's
`CORS_ORIGIN_REGEX=https://.*\.vercel\.app` already allows your production **and**
preview URLs.

Only if you attach a **custom domain** (not `*.vercel.app`): in Render → the
service → **Environment**, add `CORS_ORIGINS` = your domain (e.g.
`https://whereto.com`) and save (this redeploys).

Test: open the Vercel URL, plan a Hong Kong trip, confirm the itinerary streams
in and renders.

---

## Environment variables at a glance

| Where    | Variable                | Value                                            |
|----------|-------------------------|--------------------------------------------------|
| Render   | `SERPAPI_API_KEY`       | your key                                         |
| Render   | `GOOGLE_MAPS_API_KEY`   | your key (Places API New + Routes API enabled)   |
| Render   | `GROQ_API_KEY`          | your key                                          |
| Render   | `CORS_ORIGIN_REGEX`     | `https://.*\.vercel\.app` (from blueprint)       |
| Render   | `CORS_ORIGINS`          | *(optional)* only for a custom (non-vercel.app) domain |
| Vercel   | `NEXT_PUBLIC_API_URL`   | `https://<your-service>.onrender.com`            |

Secrets never live in the repo — `backend/.env` is gitignored; hosts inject them.
