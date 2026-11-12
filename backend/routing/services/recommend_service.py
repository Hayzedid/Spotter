"""Route ranking.

Order of preference (the assessment's list, plus two safety rules up front):
  0. Routes with complete weather data before routes with Unknown checkpoints
  1. Fewest No Travel miles
  2. Fewest Severe miles
  3. Fewest High miles
  4. Lowest average risk (mile-weighted, 0 = Low ... 4 = No Travel)
  5. Shortest travel time

Steps 0-3 are strict. For step 4, average-risk differences smaller than
AVG_RISK_TOLERANCE count as a tie so travel time decides: otherwise a single
'Moderate' checkpoint (average 0.04 vs 0.00) could make the app recommend a
route hours slower, which isn't the balance of risk and time the spec asks for.
"""
from itertools import groupby

AVG_RISK_TOLERANCE = 0.25


def _strict_key(route):
    summary = route.get('risk_summary', {})
    miles = summary.get('risk_miles', {})
    return (
        bool(summary.get('has_unknown')),
        round(miles.get('No Travel', 0.0), 1),
        round(miles.get('Severe', 0.0), 1),
        round(miles.get('High', 0.0), 1),
    )


def _avg(route):
    avg = route.get('risk_summary', {}).get('avg_risk_score')
    return avg if avg is not None else float('inf')


def _order_by_risk_then_time(group):
    """Take the lowest-average route plus every route within the tolerance of it, fastest first; repeat."""
    remaining = sorted(group, key=lambda r: (_avg(r), r.get('duration_seconds', 0)))
    ordered = []
    while remaining:
        best = _avg(remaining[0])
        band = [r for r in remaining if _avg(r) <= best + AVG_RISK_TOLERANCE]
        ordered.extend(sorted(band, key=lambda r: (r.get('duration_seconds', 0), _avg(r))))
        remaining = [r for r in remaining if r not in band]
    return ordered


def recommend_routes(routes):
    """Return routes sorted best-first with `rank` (1-based) and `recommended` set."""
    ranked = []
    for _, group in groupby(sorted(routes, key=_strict_key), key=_strict_key):
        ranked.extend(_order_by_risk_then_time(list(group)))
    for i, route in enumerate(ranked):
        route['rank'] = i + 1
        route['recommended'] = i == 0
    return ranked
