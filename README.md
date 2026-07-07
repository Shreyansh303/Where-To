# Where To — a grounded, agentic AI travel agent

Give it an origin, a destination, dates and a budget — it plans the whole trip from **live data**: real flights, a real hotel, a day-by-day itinerary of real attractions with real opening hours, meals along the route, and local-transport insight. **Every concrete fact in the output is traceable to a specific API response. Nothing is invented.**

Python + FastAPI backend · Next.js + Tailwind frontend · Groq (`llama-3.3-70b-versatile`) for orchestration and research.

## Why this project is interesting

Most "AI trip planner" demos prompt an LLM and print whatever it hallucinates. This project is built around a few engineering ideas instead:

1. **Agentic tool orchestration.** The LLM drives a real tool-calling loop (`search_flights → get_return_flights → search_hotels → search_attractions → finalize_plan`) to choose flights and a hotel — but it can only *select* options a tool returned, never *author* data. Its answer is a set of ids validated against a grounding store.

2. **Grounding enforced structurally, not by prompt.** Every entity parsed from an API response is registered in a **grounding store** and assigned an id (`flight_out_2`, `hotel_0`, `poi_7`). The LLM only ever sees compact summaries carrying those ids, and the final plan is assembled *exclusively* by resolving ids back to stored API objects — so there is no code path for an invented price or place to reach the output. An unknown id, a duplicate, or a return-flight id in the outbound slot is rejected and bounced back for a retry.

3. **Deterministic itinerary construction.** A solver — not the LLM — turns attractions into a schedule. Whole-day attractions (theme parks, island excursions) each claim a day of their own; the remaining days are packed geographically up to a per-day **time budget** rather than a fixed count. Within a day, nearest-neighbor + 2-opt orders stops over a real travel-time matrix, and a timeline walk enforces opening hours and the daily budget — lowest-value stops overflow into "if you have time" extras rather than vanishing. Breakfast/lunch/dinner are inserted from a restaurant pool near the route.

4. **Iconic-first attraction selection.** Which attractions make the trip is decided deterministically, not left to the model's taste: the grounded pool is ranked by a web-researched **must-see list** first, then by review volume, so a city's famous landmarks are never crowded out by obscure ones. Every researched must-see is grounded via a targeted Places lookup and force-included as a candidate.

5. **Web-grounded planning facts.** A research step runs a few cached web searches per city and distills them, in one LLM extraction pass, into a **city brief**: the canonical must-see list, per-attraction visit durations, whole-day flags, and ticket prices with source links. These drive the solver's durations and the displayed prices. They are clearly labelled *researched estimates* with citations — a real step up from the model guessing, but deliberately not treated as API-grounded the way flights and hotels are.

6. **Real-world data handling.** A SQLite response cache keyed by request signature (per-service TTLs; a re-planned trip costs **zero** API calls), exponential backoff on 429/5xx, a typed error taxonomy, and graceful degradation: hotels failing doesn't kill the flights or itinerary; routes failing falls back to *flagged* distance-based estimates; a failed research step falls back to duration heuristics and an LLM price estimate; an LLM outage falls back to a deterministic selection policy — every degradation is surfaced in a `data_quality` section of the plan.

## Architecture

```
frontend (Next.js)                     backend (FastAPI)
+--------------------+   POST /api/trips   +--------------------------------------+
| form -> progress ->| ------------------> | api/          jobs + SSE progress    |
| results (SSE-fed)  | <------------------ | orchestrator/ LLM tool loop (Groq)   |
+--------------------+   GET .../events    |   tools.py    toolbox + schemas      |
                        GET .../{id}       |   pipeline.py agent + deterministic  |
                                           | research/     web-grounded city brief|
                                           | grounding/    id store + validation  |
                                           | solver/       day packing.2-opt.sched|
                                           | clients/      SerpApi + Google APIs   |
                                           | cache/        SQLite, request-sig     |
                                           | output/       plan assembly (grounded)|
                                           +--------------------------------------+
```

**Request lifecycle:** `POST /api/trips` starts a job → the agent loop selects flights and a hotel (each tool: cache → API client → grounding store → id-bearing summary to the LLM) → the deterministic phase researches the city brief, grounds and ranks attractions (must-see + popularity), fetches restaurants and the travel-time matrix, runs the solver, resolves costs, and assembles the plan by id resolution → the frontend, fed live stage events over SSE, renders the result.

**Round-trip flights** use SerpApi's two-call flow: the chosen outbound option's `departure_token` fetches matching return flights; return-leg prices are the final round-trip totals, which is what the budget check uses.

## API call budget (one full plan, cold cache)

| Source | Calls | Notes |
|---|---|---|
| SerpApi Google Flights | 2 | outbound + return (`departure_token`) |
| SerpApi Google Hotels | 1 | one search for the whole stay |
| SerpApi Google Search | ~3 | web research for the city brief |
| Google Places (New) | 5–13 | 4 broad attraction queries + 1 restaurant search + up to 8 targeted must-see lookups; field masks make detail calls unnecessary |
| Google Routes | 1–5 | `computeRouteMatrix`, chunked to ≤100 elements/request |
| Groq | 6–9 | tool-calling turns + one brief-extraction call |

Re-running the same trip within the TTL window: **0** external calls (verified by per-client call counters). Flights/hotels TTL is 1h to mirror SerpApi's own cache; places/routes 24h; research 30 days.

## Testing

61 tests, no live keys required — the entire pipeline (agent loop, grounding, research, solver, assembly) can run against recorded fixture responses with a scripted LLM policy, which also powers zero-cost CI.

- **Solver**: synthetic-geometry tests — time-budget day packing, full-day attractions isolated to their own day, 2-opt reaching the brute-force optimum, opening-hours swaps/waits/drops, value-ordered overflow into extras, meal insertion, determinism.
- **Grounding**: unknown/duplicate/wrong-type id rejection; a provenance test asserting every price and name in an assembled plan exists byte-for-byte in the recorded API fixtures.
- **Orchestrator**: full pipeline over fixture-backed clients; must-see force-inclusion vs. popular-but-generic POIs; the invalid-selection retry path; hotels-down and routes-down degradation; the budget-rejection flow.
- **Research**: web-snippet parsing, city-brief extraction into structured facts, and graceful `None` fallback on failure.
- **Clients**: fixture parsing (incl. the `departure_token` flow), retry/backoff on 429, auth errors not retried, cache preventing repeat HTTP calls.

## The solver, honestly

Greedy nearest-neighbor + 2-opt is not globally optimal (a small TSP-ish heuristic that's easy to reason about and test); one opening window per visit is honored (no split visits or timed-entry tickets); meal travel legs use distance-based estimates by design (restaurants are chosen *because* they're adjacent to the route). Attractions that can't fit surface as unscheduled extras rather than disappearing. Visit durations and ticket prices are researched estimates with sources, not booking-grade data.

