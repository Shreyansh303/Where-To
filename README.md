# 🧭 Where To — a grounded, agentic AI travel agent

Give it an origin, a destination, dates, a budget and your interests — it plans the whole trip from **live data**: real flights, a real hotel, a day-by-day itinerary of real attractions with real opening hours, meals along the route, and local-transport insight. **Every concrete fact in the output is traceable to a specific API response. Nothing is invented.**

Python + FastAPI backend · Next.js + Tailwind frontend · Groq (`llama-3.3-70b-versatile`) for orchestration.

## Why this project is interesting

Most "AI trip planner" demos prompt an LLM and print whatever it hallucinates. This project is built around four engineering ideas instead:

1. **Agentic tool orchestration.** The LLM drives a real tool-calling loop (`search_flights → get_return_flights → search_hotels → search_attractions → finalize_plan`) and decides what to call and what to pick — but it can only *select*, never *author*, data.
2. **Grounding enforced structurally, not by prompt.** Every entity parsed from an API response is registered in a **grounding store** and assigned an id (`flight_out_2`, `hotel_0`, `poi_7`). The LLM only ever sees compact summaries carrying those ids, and its final answer is a set of id selections validated against the store — an unknown id, a duplicate, or a return-flight id in the outbound slot is rejected and bounced back for a retry. The final plan is assembled *exclusively* by resolving ids back to stored API objects, so there is no code path for an invented price or place to reach the output.
3. **Constraint solving as real code.** A deterministic solver — not the LLM — turns selected attractions into a schedule: balanced k-means clusters POIs into one geographic cluster per day (minimizes backtracking), nearest-neighbor + 2-opt orders each day over a real travel-time matrix, a timeline walk enforces opening hours and a daily time budget (dropping lowest-value POIs first, with explicit reasons), and breakfast/lunch/dinner are inserted from a restaurant pool near the route.
4. **Real-world data handling.** SQLite response cache keyed by request signature (per-service TTLs; a re-planned trip costs **zero** API calls), exponential backoff on 429/5xx, a typed error taxonomy, and graceful degradation: hotels failing doesn't kill the flights or itinerary; routes failing falls back to *flagged* distance-based estimates; an LLM outage falls back to a deterministic selection policy — every degradation is surfaced in a `data_quality` section of the plan.

## Architecture

```
frontend (Next.js)                     backend (FastAPI)
┌────────────────────┐   POST /api/trips   ┌──────────────────────────────────────┐
│ form → progress →  │ ───────────────────▶│ api/        jobs + SSE progress      │
│ results (SSE-fed)  │◀─────────────────── │ orchestrator/  LLM tool loop (Groq)  │
└────────────────────┘   GET …/events      │   ├─ tools.py    toolbox + schemas   │
                         GET …/{id}        │   └─ pipeline.py agent + determinism │
                                           │ grounding/  id store + validation    │
                                           │ solver/     clustering·2-opt·schedule│
                                           │ clients/    SerpApi ✈️🏨 Google 🗺️🚇  │
                                           │ cache/      SQLite, request-signature│
                                           │ output/     plan assembly (grounded) │
                                           └──────────────────────────────────────┘
```

**Request lifecycle:** `POST /api/trips` starts a job → the agent loop runs tools (each tool: cache → API client → grounding store → id-bearing summary to the LLM) → `finalize_plan` validates the LLM's id selections (+ budget check) → the deterministic phase fetches restaurants + the travel-time matrix, runs the solver, and assembles the plan by id resolution → the frontend, fed live stage events over SSE, renders the result.

**Round-trip flights** use SerpApi's two-call flow: the chosen outbound option's `departure_token` fetches matching return flights; return-leg prices are the final round-trip totals, which is what the budget check uses.

## API call budget (one full plan, cold cache)

| Source | Calls | Notes |
|---|---|---|
| SerpApi Google Flights | 2 | outbound + return (`departure_token`) |
| SerpApi Google Hotels | 1 | one search for the whole stay |
| Google Places (New) | 3–6 | 1 per interest (capped at 5) + 1 restaurant search; field masks make detail calls unnecessary |
| Google Routes | 1–5 | `computeRouteMatrix`, chunked to ≤100 elements/request |
| Groq | 5–8 | tool-calling turns |

Re-running the same trip within the TTL window: **0** external calls (verified by per-client call counters). Flights/hotels TTL is 1h to mirror SerpApi's own cache; places/routes 24h.

## Quickstart

Prereqs: Python 3.11+, Node 18+.

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                              # add your real keys
uvicorn app.api.main:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                                       # http://localhost:3000
```

**No keys? Demo mode.** Set `FAKE_APIS=1` in `backend/.env` and the entire pipeline — agent loop, grounding, solver, UI — runs against recorded fixture responses with a scripted LLM policy. Zero API spend, fully deterministic (fake mode uses its own cache file so it never replays live data).

Keys you need for live mode (see `backend/.env.example`): `SERPAPI_API_KEY` (Google Flights + Hotels), `GOOGLE_MAPS_API_KEY` (Places API New + Routes API — Routes requires billing enabled on the Google Cloud project; without it the app degrades to flagged distance-based travel estimates), `GROQ_API_KEY`.

## Testing

```bash
cd backend && python -m pytest        # 51 tests
```

- **Solver**: synthetic-geometry tests — clustering balance, 2-opt reaches the brute-force optimum, opening-hours swaps/waits/drops, time-budget trimming (lowest value first), meal insertion, determinism.
- **Grounding**: unknown/duplicate/wrong-type id rejection; a provenance test asserting every price and name in an assembled plan exists byte-for-byte in the recorded API fixtures.
- **Orchestrator**: full pipeline over fixture-backed clients with the scripted LLM; the invalid-selection retry path; hotels-down and routes-down degradation; budget-rejection flow.
- **Clients**: fixture parsing (incl. the `departure_token` flow), retry/backoff on 429, auth errors not retried, cache preventing repeat HTTP calls.

No live keys are needed for any test.

## The solver, honestly

Greedy nearest-neighbor + 2-opt is not globally optimal (it's a small TSP-ish heuristic that's easy to reason about and test); one opening window per visit is honored (no split visits or timed-entry tickets); meal travel legs use distance-based estimates by design (restaurants are chosen *because* they're adjacent to the route). POIs that can't fit are dropped with explicit, user-visible reasons — never silently.

## Deliberate MVP exclusions

Booking flow (SerpApi `booking_token` — post-selection, not core), multi-city trips, user accounts / persistent job storage (in-memory jobs, single process), currency conversion (single configurable currency, default INR), `deep_search` (exposed as a client flag, default off), map rendering (timeline + ordering instead), streaming LLM tokens (stage events are the progress signal).
