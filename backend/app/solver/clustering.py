"""Balanced geographic clustering of POIs — one cluster per itinerary day.

Plain k-means (pure Python, deterministic seed) over lat/lng with longitude
scaled by cos(latitude) so distances are locally euclidean, followed by a
capacity-bounded reassignment so no day is overloaded while another sits
nearly empty. City-scale coordinates make this accurate enough; no external
dependency needed for ≤ ~40 points.
"""

import math
import random

from ..models import POI


def _coords(poi: POI, lng_scale: float) -> tuple[float, float]:
    return (poi.location.lat, poi.location.lng * lng_scale)


def _dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def cluster_pois(pois: list[POI], k: int, seed: int = 42) -> list[list[POI]]:
    """Partition POIs into k balanced geographic clusters (capacity ⌈n/k⌉)."""
    if k <= 0:
        raise ValueError("k must be positive")
    if k == 1 or len(pois) <= k:
        return [pois[i::k] for i in range(k)] if len(pois) > k else _trivial(pois, k)

    lng_scale = math.cos(math.radians(sum(p.location.lat for p in pois) / len(pois)))
    points = [_coords(p, lng_scale) for p in pois]
    rng = random.Random(seed)

    # k-means++ style init: spread the initial centroids out.
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

    # Capacity-bounded reassignment: points with the most to lose from being
    # bumped off their nearest centroid ("regret") pick first.
    capacity = math.ceil(len(pois) / k)
    order = sorted(
        range(len(points)),
        key=lambda i: -_regret(points[i], centroids),
    )
    counts = [0] * k
    final = [0] * len(points)
    for i in order:
        ranked = sorted(range(k), key=lambda c: _dist2(points[i], centroids[c]))
        target = next((c for c in ranked if counts[c] < capacity), ranked[0])
        final[i] = target
        counts[target] += 1

    clusters: list[list[POI]] = [[] for _ in range(k)]
    for i, c in enumerate(final):
        clusters[c].append(pois[i])
    return clusters


def _regret(pt: tuple[float, float], centroids: list[tuple[float, float]]) -> float:
    dists = sorted(_dist2(pt, c) for c in centroids)
    return dists[1] - dists[0] if len(dists) > 1 else 0.0


def _trivial(pois: list[POI], k: int) -> list[list[POI]]:
    clusters: list[list[POI]] = [[] for _ in range(k)]
    for i, p in enumerate(pois):
        clusters[i % k].append(p)
    return clusters
