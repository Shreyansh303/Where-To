"""Geographic day-packing of POIs — one cluster per itinerary day.

Plain k-means (pure Python, deterministic seed) over lat/lng with longitude
scaled by cos(latitude) so distances are locally euclidean. Two entry points:

- `cluster_pois` — pure geographic partition into k groups.
- `pack_days` — the solver's day builder: full-day attractions (theme parks,
  island excursions) each claim a day of their own; the rest are grouped
  geographically into the remaining days and filled up to a per-day *time
  budget* (not a fixed count). POIs that don't fit are left out and surface
  later as unscheduled "if you have time" extras.

City-scale coordinates make this accurate enough; no external dependency
needed for ≤ ~40 points.
"""

import math
import random

from ..models import POI

Point = tuple[float, float]


def _lng_scale(pois: list[POI]) -> float:
    return math.cos(math.radians(sum(p.location.lat for p in pois) / len(pois)))


def _coords(poi: POI, lng_scale: float) -> Point:
    return (poi.location.lat, poi.location.lng * lng_scale)


def _dist2(a: Point, b: Point) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _regret(pt: Point, centroids: list[Point]) -> float:
    dists = sorted(_dist2(pt, c) for c in centroids)
    return dists[1] - dists[0] if len(dists) > 1 else 0.0


def _kmeans(points: list[Point], k: int, seed: int) -> list[Point]:
    """k-means++ init + Lloyd's iteration; returns k centroids."""
    rng = random.Random(seed)
    centroids = [points[rng.randrange(len(points))]]
    while len(centroids) < k:
        dists = [min(_dist2(pt, c) for c in centroids) for pt in points]
        total = sum(dists) or 1.0
        r, acc, chosen = rng.random() * total, 0.0, len(points) - 1
        for i, d in enumerate(dists):
            acc += d
            if acc >= r:
                chosen = i
                break
        centroids.append(points[chosen])

    assignment = [0] * len(points)
    for _ in range(50):
        new_assignment = [min(range(k), key=lambda c: _dist2(pt, centroids[c])) for pt in points]
        if new_assignment == assignment:
            break
        assignment = new_assignment
        for c in range(k):
            members = [points[i] for i in range(len(points)) if assignment[i] == c]
            if members:
                centroids[c] = (
                    sum(m[0] for m in members) / len(members),
                    sum(m[1] for m in members) / len(members),
                )
    return centroids


def cluster_pois(pois: list[POI], k: int, seed: int = 42) -> list[list[POI]]:
    """Partition POIs into k geographic clusters (no capacity constraint)."""
    if k <= 0:
        raise ValueError("k must be positive")
    if k == 1 or len(pois) <= k:
        return _trivial(pois, k)
    lng_scale = _lng_scale(pois)
    points = [_coords(p, lng_scale) for p in pois]
    centroids = _kmeans(points, k, seed)
    clusters: list[list[POI]] = [[] for _ in range(k)]
    for p, pt in zip(pois, points):
        clusters[min(range(k), key=lambda c: _dist2(pt, centroids[c]))].append(p)
    return clusters


def pack_days(pois: list[POI], k: int, day_budget_minutes: int, seed: int = 42) -> list[list[POI]]:
    """Build k day-clusters. Full-day attractions each take a day of their own;
    the rest are grouped geographically and packed up to `day_budget_minutes`
    of visit time per day. Overflow POIs are omitted (they become extras)."""
    if k <= 0:
        raise ValueError("k must be positive")

    full = sorted((p for p in pois if p.full_day), key=lambda p: -p.value_score)
    full_days, surplus = full[:k], full[k:]
    # A full-day attraction with no day to spare rejoins the normal pool; it
    # will overflow a shared day's budget and surface as an extra, not silently
    # crowd out everything else.
    rest = [p for p in pois if not p.full_day] + surplus

    clusters: list[list[POI]] = [[fd] for fd in full_days]
    remaining = k - len(full_days)
    if remaining <= 0:
        return clusters  # every day is a full-day outing; `rest` becomes extras

    clusters.extend(_pack_geographic(rest, remaining, day_budget_minutes, seed))
    return clusters


def _pack_geographic(pois: list[POI], k: int, day_budget_minutes: int, seed: int) -> list[list[POI]]:
    """Group POIs into k geographic day-clusters, each capped at a visit-time
    budget. Points that don't fit any nearby day are dropped from the result."""
    clusters: list[list[POI]] = [[] for _ in range(k)]
    if not pois:
        return clusters
    if len(pois) <= k:
        for i, p in enumerate(pois):
            clusters[i % k].append(p)
        return clusters

    lng_scale = _lng_scale(pois)
    points = [_coords(p, lng_scale) for p in pois]
    centroids = _kmeans(points, k, seed)

    # Most valuable POIs claim their (nearest) day first, so when a day's time
    # budget is tight it is the lowest-value stops that overflow into extras.
    # Regret breaks ties, keeping geographically committed points on their day.
    order = sorted(
        range(len(points)),
        key=lambda i: (-pois[i].value_score, -_regret(points[i], centroids)),
    )
    minutes = [0] * k
    for i in order:
        poi = pois[i]
        ranked = sorted(range(k), key=lambda c: _dist2(points[i], centroids[c]))
        target = next(
            (c for c in ranked if minutes[c] + poi.est_visit_minutes <= day_budget_minutes),
            None,
        )
        if target is None:
            continue  # no day has room — leave unscheduled (surfaces as an extra)
        clusters[target].append(poi)
        minutes[target] += poi.est_visit_minutes
    return clusters


def _trivial(pois: list[POI], k: int) -> list[list[POI]]:
    clusters: list[list[POI]] = [[] for _ in range(k)]
    for i, p in enumerate(pois):
        clusters[i % k].append(p)
    return clusters
