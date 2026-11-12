"""Weather grid along the trip corridor and the 0-48 h heatmap frames.

The grid follows every route's actual road geometry with a row of points on
each side, so the heatmap covers the whole corridor. Each frame stores per-point
risk scores (overall, and per condition) which the frontend interpolates into a
continuous field.
"""
from datetime import timedelta

from .geo import cumulative_distances, interpolate_point, offset_point, perpendicular_unit, haversine
from .risk_service import classify_checkpoint, RISK_SCORES
from .weather_service import HOUR_FMT, fetch_hourly, forecast_horizon, to_utc_naive, weather_at_hour

HEATMAP_HOURS = 48
TARGET_CENTERLINE_POINTS = 45   # per longest route; total grid is ~3x this after lateral rows and merging
MAX_GRID_POINTS = 180
MIN_SPACING_MILES = 3.0


def _points_along(coords, spacing):
    """[lng, lat] points every `spacing` miles along a polyline, with the local heading at each."""
    cum = cumulative_distances(coords)
    out = []
    target = 0.0
    for i in range(1, len(coords)):
        seg = cum[i] - cum[i - 1]
        while seg > 0 and target <= cum[i]:
            f = (target - cum[i - 1]) / seg
            out.append((interpolate_point(coords[i - 1], coords[i], f), coords[i - 1], coords[i]))
            target += spacing
    # Always include the route's end so the corridor reaches the destination
    if cum[-1] - (target - spacing) > 0.3 * spacing:
        out.append((coords[-1], coords[-2], coords[-1]))
    return out


def build_corridor_grid(routes):
    """Return (points, spacing_miles); points are (lat, lng) tuples."""
    geometries = [r['geometry'] for r in routes if len(r.get('geometry', [])) >= 2]
    if not geometries:
        return [], 0.0
    longest = max(cumulative_distances(g)[-1] for g in geometries)
    spacing = max(MIN_SPACING_MILES, longest / TARGET_CENTERLINE_POINTS)

    while True:
        points = []
        for geom in geometries:
            for centre, a, b in _points_along(geom, spacing):
                east, north = perpendicular_unit(a, b)
                for side in (0.0, 1.0, -1.0):
                    p = offset_point(centre, east * side * spacing, north * side * spacing)
                    if all(haversine(p, q) >= 0.6 * spacing for q in points):
                        points.append(p)
        if len(points) <= MAX_GRID_POINTS:
            break
        spacing *= 1.15
    return [(round(p[1], 4), round(p[0], 4)) for p in points], round(spacing, 2)


def heatmap_from_weather(points, spacing, departure_time, load_weight, weather_fn, horizon=None):
    """Build the 49 hourly frames from `weather_fn(point_index, datetime) -> weather dict | None`.

    Frames past `horizon` (the forecast limit) are marked unavailable.
    """
    dep = to_utc_naive(departure_time).replace(minute=0, second=0, microsecond=0)
    hours = []
    for offset in range(HEATMAP_HOURS + 1):
        when = dep + timedelta(hours=offset)
        frame = {
            'offset': offset,
            'time': when.strftime(HOUR_FMT),
            'available': horizon is None or when <= horizon,
            'risk': [], 'wind': [], 'rain': [], 'snow': [],
        }
        if frame['available']:
            for i in range(len(points)):
                risk = classify_checkpoint(weather_fn(i, when), load_weight)
                frame['risk'].append(risk['score'])
                for key in ('wind', 'rain', 'snow'):
                    frame[key].append(RISK_SCORES.get(risk[f'{key}_risk']))
            frame['available'] = any(s is not None for s in frame['risk'])
        hours.append(frame)

    return {
        'departure_time': dep.isoformat() + 'Z',
        'spacing_miles': spacing,
        'points': [[lat, lng] for lat, lng in points],
        'hours': hours,
    }


def fetch_corridor_heatmap(points, spacing, departure_time, load_weight):
    """Real-forecast heatmap: one batched Open-Meteo lookup for the whole 0-48 h window."""
    dep = to_utc_naive(departure_time)
    series = fetch_hourly(points, dep, dep + timedelta(hours=HEATMAP_HOURS + 1))
    return heatmap_from_weather(
        points, spacing, departure_time, load_weight,
        weather_fn=lambda i, when: weather_at_hour(series[i] if i < len(series) else None, when),
        horizon=forecast_horizon(),
    )
