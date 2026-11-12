"""Geocoding, truck routing and checkpoint generation.

Routing strategy
----------------
1. OpenRouteService (ORS) `driving-hgv` (truck profile) is the primary provider.
   - The main route is a direct origin -> destination request.
   - Short trips first try ORS's built-in `alternative_routes` (ORS only allows it
     for routes up to ~100 km).
   - Remaining alternatives are found by forcing the route through detour
     waypoints placed to either side of the trip's midpoint. Each candidate is
     still truck-routed and is kept only if it is clearly distinct from the
     routes already found and not an absurd detour.
2. If ORS is unavailable (no key, quota exhausted, outage) everything falls back
   to public OSRM, which only offers a car profile. The response then carries a
   notice so the UI can tell the driver that travel times are car estimates.

Routes are never mixed across providers, so travel times stay comparable.
"""
import hashlib
import logging
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import requests
from django.conf import settings
from django.core.cache import cache

from .errors import RoutingInputError, UpstreamServiceError
from .geo import (
    cumulative_distances,
    haversine,
    interpolate_point,
    miles_per_degree_lng,
    offset_point,
    perpendicular_unit,
)

logger = logging.getLogger(__name__)

ORS_BASE_URL = 'https://api.openrouteservice.org'
OSRM_BASE_URL = 'https://router.project-osrm.org'
NOMINATIM_BASE_URL = 'https://nominatim.openstreetmap.org'
USER_AGENT = 'SpotterWeatherRouting/1.0'

PROVIDER_ORS_HGV = 'openrouteservice-hgv'
PROVIDER_OSRM_CAR = 'osrm-car'

TARGET_ROUTE_COUNT = 3
GEOCODE_CACHE_SECONDS = 24 * 3600
ROUTE_CACHE_SECONDS = 15 * 60

# Alternative-route acceptance rules
MAX_DETOUR_DURATION_FACTOR = 1.6   # reject alternatives > 60% slower than the fastest route
MAX_SHARED_FRACTION = 0.8          # reject alternatives sharing > 80% of their path with an existing route
SHARED_DISTANCE_MILES = 1.5        # points closer than this to another route count as "shared"
ORS_ALTERNATIVES_MAX_MILES = 55    # straight-line distance below which ORS alternative_routes is attempted
# Detour waypoint offsets, as a fraction of the straight-line trip length, tried in order
DETOUR_OFFSETS = [0.15, -0.15, 0.3, -0.3, 0.45, -0.45]

ORS_ERR_NO_ROUTE = (2009, 2010)      # route not found / point not routable
OSRM_NO_ROUTE_CODES = ('NoRoute', 'NoSegment')
NO_ROUTE_MESSAGE = (
    'No drivable route was found between these locations. Check the place names: '
    'a misspelled place may have matched somewhere far away.'
)

CHECKPOINT_INTERVALS = (10.0, 25.0, 50.0)
MIN_SEGMENTS = 4                   # a requested interval must give the shortest route >= 4 gaps
MAIN_ROAD_MIN_SHARE = 0.25         # a highway is named only if it carries >= 25% of the route
SIDE_LABEL_MIN_FRACTION = 0.03     # routes must differ by >= 3% of trip length to get side labels
METERS_TO_MILES = 0.000621371


# --------------------------------------------------------------------------- geocoding

def geocode(place_name):
    """Return [lng, lat] for a place name (Nominatim, then the ORS geocoder). Cached for 24 h.

    Nominatim goes first because it resolves cities to their actual centre
    (ORS placed 'Washington, DC' several miles south of downtown).
    """
    key = 'geocode:' + hashlib.sha1(place_name.strip().lower().encode('utf-8')).hexdigest()
    cached = cache.get(key)
    if cached:
        return cached

    coords = _geocode_nominatim(place_name) or _geocode_ors(place_name)
    if not coords:
        raise RoutingInputError(f"Could not find a location named '{place_name}'.")
    cache.set(key, coords, GEOCODE_CACHE_SECONDS)
    return coords


def _ors_key():
    return getattr(settings, 'ORS_API_KEY', '').strip()


def _geocode_ors(place_name):
    if not _ors_key():
        return None
    try:
        resp = requests.get(
            f'{ORS_BASE_URL}/geocode/search',
            params={'api_key': _ors_key(), 'text': place_name, 'size': 1},
            timeout=8,
        )
        resp.raise_for_status()
        features = resp.json().get('features', [])
        if features:
            return features[0]['geometry']['coordinates'][:2]
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.warning('ORS geocoding failed for %r: %s', place_name, exc)
    return None


def _geocode_nominatim(place_name):
    try:
        resp = requests.get(
            f'{NOMINATIM_BASE_URL}/search',
            params={'q': place_name, 'format': 'json', 'limit': 1},
            headers={'User-Agent': USER_AGENT},
            timeout=8,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return [float(results[0]['lon']), float(results[0]['lat'])]
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.warning('Nominatim geocoding failed for %r: %s', place_name, exc)
    return None


# --------------------------------------------------------------------------- providers

def _distribute(total, weights):
    """Split `total` across segments proportionally to `weights` (equal split if all zero)."""
    s = sum(weights)
    if s <= 0:
        return [total / len(weights)] * len(weights) if weights else []
    return [total * w / s for w in weights]


def _times_from_ors_steps(coords, segments):
    """Cumulative seconds at every coordinate, using each ORS step's own duration.

    Step `way_points` are [start, end] indices into the full geometry; a step's
    duration is spread over its coordinates in proportion to distance, so slow
    city streets and fast interstates keep their real speeds.
    """
    seg_seconds = [0.0] * max(0, len(coords) - 1)
    for segment in segments:
        for step in segment.get('steps', []):
            a, b = step.get('way_points', [0, 0])
            if b <= a:
                continue
            lengths = [haversine(coords[i], coords[i + 1]) for i in range(a, b)]
            for i, sec in zip(range(a, b), _distribute(step.get('duration', 0.0), lengths)):
                seg_seconds[i] = sec
    return _cumulative(seg_seconds)


def _cumulative(segment_values):
    out = [0.0]
    for v in segment_values:
        out.append(out[-1] + v)
    return out


def _parse_ors_feature(feature):
    coords = [c[:2] for c in feature['geometry']['coordinates']]
    props = feature.get('properties', {})
    summary = props.get('summary', {})
    segments = props.get('segments', [])
    roads = OrderedDict()
    for segment in segments:
        for step in segment.get('steps', []):
            _add_road(roads, step.get('name'), step.get('distance', 0.0))
    times = _times_from_ors_steps(coords, segments)
    return _route_record(coords, summary.get('distance', 0.0), summary.get('duration', 0.0), times, roads)


def _route_record(coords, distance_m, duration_s, times, roads):
    # Rescale the per-coordinate times so they add up exactly to the provider's total duration
    if times and times[-1] > 0 and duration_s > 0:
        k = duration_s / times[-1]
        times = [t * k for t in times]
    elif len(coords) > 1:
        times = _cumulative(_distribute(duration_s, [
            haversine(coords[i], coords[i + 1]) for i in range(len(coords) - 1)
        ]))
    return {
        'geometry': [[round(c[0], 5), round(c[1], 5)] for c in coords],
        'distance_meters': distance_m,
        'duration_seconds': duration_s,
        'coord_times': times,
        'roads': roads,
    }


def _ors_directions(coordinates, alternatives=False):
    """Call ORS driving-hgv. Returns a list of parsed routes; raises UpstreamServiceError on failure."""
    body = {
        'coordinates': coordinates,
        'instructions': True,
        # -1 = snap each waypoint to the nearest road however far away (detour points may land off-road)
        'radiuses': [-1] * len(coordinates),
    }
    if alternatives:
        body['alternative_routes'] = {'target_count': 3, 'share_factor': 0.6, 'weight_factor': 1.6}
    try:
        resp = requests.post(
            f'{ORS_BASE_URL}/v2/directions/driving-hgv/geojson',
            json=body,
            headers={'Authorization': _ors_key(), 'Content-Type': 'application/json'},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise UpstreamServiceError(f'OpenRouteService unreachable: {exc}') from exc

    if resp.status_code != 200:
        code = _ors_error_code(resp)
        # Over ORS's 6,000 km limit is treated like ORS being unavailable: OSRM gets a try,
        # and if OSRM finds no road either, the user gets NO_ROUTE_MESSAGE.
        if resp.status_code == 404 or code in ORS_ERR_NO_ROUTE:
            return []
        raise UpstreamServiceError(f'OpenRouteService returned {resp.status_code}: {resp.text[:200]}')
    return [_parse_ors_feature(f) for f in resp.json().get('features', [])]


def _ors_error_code(resp):
    try:
        return resp.json().get('error', {}).get('code')
    except (ValueError, AttributeError):
        return None


def _osrm_route(waypoints, alternatives=False):
    """Call public OSRM (car profile). Returns a list of parsed routes."""
    path = ';'.join(f'{lng:.5f},{lat:.5f}' for lng, lat in waypoints)
    params = {
        'overview': 'full',
        'geometries': 'geojson',
        'steps': 'true',
        'annotations': 'duration',
        'alternatives': 'true' if alternatives else 'false',
    }
    try:
        resp = requests.get(f'{OSRM_BASE_URL}/route/v1/driving/{path}', params=params, timeout=20)
        if resp.status_code == 400 and resp.json().get('code') in OSRM_NO_ROUTE_CODES:
            return []   # valid request, but no road connects the points
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamServiceError(f'OSRM routing failed: {exc}') from exc

    routes = []
    for r in data.get('routes', []):
        coords = r.get('geometry', {}).get('coordinates', [])
        if len(coords) < 2:
            continue
        roads = OrderedDict()
        edge_durations = []
        for leg in r.get('legs', []):
            edge_durations.extend(leg.get('annotation', {}).get('duration', []))
            for step in leg.get('steps', []):
                _add_road(roads, step.get('ref') or step.get('name'), step.get('distance', 0.0))
        times = _cumulative(edge_durations) if len(edge_durations) == len(coords) - 1 else []
        routes.append(_route_record(coords, r.get('distance', 0.0), r.get('duration', 0.0), times, roads))
    return routes


# --------------------------------------------------------------------------- road names

_REF_RE = re.compile(r'^(I|US|[A-Z]{2})[\s-]?(\d{1,4}[A-Z]?)\b')


def _add_road(roads, raw_name, distance_m):
    """Accumulate distance per highway reference (e.g. 'I 80 Express' -> 'I-80')."""
    if not raw_name or not distance_m:
        return
    for part in re.split(r'[,;]', raw_name):
        m = _REF_RE.match(part.strip())
        if m:
            ref = f'{m.group(1)}-{m.group(2)}'
            roads[ref] = roads.get(ref, 0.0) + distance_m
            return


def _road_priority(ref):
    if ref.startswith('I-'):
        return 0
    if ref.startswith('US-'):
        return 1
    return 2


def main_roads(roads, total_meters, limit=2):
    """Highways covering at least MAIN_ROAD_MIN_SHARE of the route, interstates first, in driving order.

    Truck routing (ORS) leaves many highway stretches unnamed, so a road is only
    named when the data clearly shows it carries a large part of the trip.
    """
    if not roads or total_meters <= 0:
        return []
    major = [(ref, d) for ref, d in roads.items() if d / total_meters >= MAIN_ROAD_MIN_SHARE]
    ranked = sorted(major, key=lambda kv: (_road_priority(kv[0]), -kv[1]))
    chosen = {ref for ref, _ in ranked[:limit]}
    return [ref for ref in roads if ref in chosen]


def mean_offset_miles(geometry, origin, dest):
    """Average signed distance of a route from the straight origin->destination line (left is positive)."""
    east, north = perpendicular_unit(origin, dest)
    lng_scale = miles_per_degree_lng((origin[1] + dest[1]) / 2)
    pts = _sample(geometry, 100)
    return sum(
        (p[0] - origin[0]) * lng_scale * east + (p[1] - origin[1]) * 69.0 * north for p in pts
    ) / len(pts)


def side_labels(geometries, origin, dest):
    """'Northern' / 'Central' / 'Southern' (or Eastern/Western for north-south trips) per route.

    Labels come from where each route actually runs relative to the straight
    trip line. Returns None for every route if they don't differ meaningfully.
    """
    n = len(geometries)
    if n < 2:
        return [None] * n
    offsets = [mean_offset_miles(g, origin, dest) for g in geometries]
    threshold = max(2.0, SIDE_LABEL_MIN_FRACTION * haversine(origin, dest))
    if max(offsets) - min(offsets) < threshold:
        return [None] * n

    east, north = perpendicular_unit(origin, dest)
    if abs(north) >= abs(east):
        left, right = ('Northern', 'Southern') if north > 0 else ('Southern', 'Northern')
    else:
        left, right = ('Eastern', 'Western') if east > 0 else ('Western', 'Eastern')

    order = sorted(range(n), key=lambda i: offsets[i])
    labels = ['Central'] * n
    labels[order[0]] = right
    labels[order[-1]] = left
    return labels


# --------------------------------------------------------------------------- alternatives

def _sample(coords, n=150):
    step = max(1, len(coords) // n)
    return coords[::step] + [coords[-1]]


def shared_fraction(candidate, existing):
    """Fraction of `candidate`'s sampled points lying within SHARED_DISTANCE_MILES of `existing`."""
    cand = _sample(candidate)
    other = _sample(existing, 300)
    shared = 0
    for p in cand:
        if any(haversine(p, q) < SHARED_DISTANCE_MILES for q in other):
            shared += 1
    return shared / len(cand)


def _is_acceptable(candidate, accepted):
    fastest = min(r['duration_seconds'] for r in accepted)
    if fastest > 0 and candidate['duration_seconds'] > fastest * MAX_DETOUR_DURATION_FACTOR:
        return False
    return all(shared_fraction(candidate['geometry'], r['geometry']) <= MAX_SHARED_FRACTION for r in accepted)


def detour_waypoints(origin, dest):
    """Detour points to either side of the trip midpoint, nearest first."""
    trip_miles = haversine(origin, dest)
    mid = interpolate_point(origin, dest, 0.5)
    east, north = perpendicular_unit(origin, dest)
    return [offset_point(mid, east * f * trip_miles, north * f * trip_miles) for f in DETOUR_OFFSETS]


def _try_route(route_fn, waypoints):
    """A detour that can't be routed (or pushes past a distance limit) just isn't an alternative."""
    try:
        return route_fn(waypoints, alternatives=False)
    except RoutingInputError:
        return []


def _collect_routes(route_fn, origin, dest, use_builtin_alternatives):
    """Main route plus distinct alternatives using one provider's `route_fn(waypoints, alternatives)`."""
    accepted = []
    candidates = route_fn([origin, dest], alternatives=use_builtin_alternatives)
    if not candidates:
        raise RoutingInputError(NO_ROUTE_MESSAGE)
    accepted.append(candidates[0])
    for cand in candidates[1:]:
        if len(accepted) < TARGET_ROUTE_COUNT and _is_acceptable(cand, accepted):
            accepted.append(cand)

    # Detours come in left/right pairs; each pair is requested in parallel to save time
    detours = detour_waypoints(origin, dest)
    for i in range(0, len(detours), 2):
        if len(accepted) >= TARGET_ROUTE_COUNT:
            break
        pair = detours[i:i + 2]
        with ThreadPoolExecutor(max_workers=len(pair)) as pool:
            results = list(pool.map(lambda via: _try_route(route_fn, [origin, via, dest]), pair))
        for found in results:
            for cand in found[:1]:
                if len(accepted) < TARGET_ROUTE_COUNT and _is_acceptable(cand, accepted):
                    accepted.append(cand)
    return accepted


def fetch_routes(origin, dest):
    """Up to 3 distinct routes from one provider: (routes, provider, notices). Cached 15 min."""
    key = 'routes:' + hashlib.sha1(repr((
        [round(c, 4) for c in origin], [round(c, 4) for c in dest], bool(_ors_key()),
    )).encode()).hexdigest()
    cached = cache.get(key)
    if cached:
        return cached

    notices = []
    routes, provider = None, None
    short_trip = haversine(origin, dest) <= ORS_ALTERNATIVES_MAX_MILES

    if _ors_key():
        try:
            routes = _collect_routes(_ors_directions, origin, dest, use_builtin_alternatives=short_trip)
            provider = PROVIDER_ORS_HGV
        except UpstreamServiceError as exc:
            logger.warning('Truck routing unavailable, falling back to OSRM: %s', exc)
            notices.append(
                'Truck routing (OpenRouteService) is unavailable right now, so routes and travel '
                'times are car estimates from OSRM. Real truck times will be longer.'
            )
    else:
        notices.append(
            'No OpenRouteService API key is configured, so routes and travel times are car '
            'estimates from OSRM. Real truck times will be longer.'
        )

    if routes is None:
        routes = _collect_routes(_osrm_route, origin, dest, use_builtin_alternatives=True)
        provider = PROVIDER_OSRM_CAR

    if len(routes) < TARGET_ROUTE_COUNT:
        notices.append(
            f'Only {len(routes)} clearly different route{"s" if len(routes) != 1 else ""} '
            f'exist between these locations.'
        )

    result = (routes, provider, notices)
    cache.set(key, result, ROUTE_CACHE_SECONDS)
    return result


# --------------------------------------------------------------------------- checkpoints

def get_checkpoint_interval(total_miles):
    """Automatic 10 / 25 / 50 mile sampling interval for a trip of this length."""
    if total_miles < 100:
        return 10.0
    if total_miles < 500:
        return 25.0
    return 50.0


def resolve_interval(requested, route_miles):
    """Pick the checkpoint interval shared by all routes. Returns (interval_miles, notice or None).

    'auto' chooses from the longest route. A requested interval that would leave
    the shortest route with fewer than MIN_SEGMENTS gaps between checkpoints is
    stepped down (50 -> 25 -> 10): with only start and end sampled, a storm in
    between would be missed entirely.
    """
    if requested in (None, '', 'auto'):
        return get_checkpoint_interval(max(route_miles) if route_miles else 0.0), None

    chosen = float(requested)
    shortest = min(route_miles) if route_miles else 0.0
    interval = chosen
    smaller = [i for i in CHECKPOINT_INTERVALS if i < interval]
    while smaller and shortest / interval < MIN_SEGMENTS:
        interval = smaller.pop()
    if interval == chosen:
        return interval, None
    return interval, (
        f'Weather is sampled every {interval:g} mi instead of {chosen:g} mi: '
        f'{chosen:g} mi is too coarse for a {shortest:.0f}-mi route and would miss weather between checkpoints.'
    )


def generate_checkpoints(coords, coord_times, total_distance_miles, departure_time, interval):
    """Place checkpoints every `interval` miles with the truck's ETA at each one.

    Mile markers use the provider's reported distance (the polyline's haversine
    length is rescaled to match it). ETAs come from per-coordinate cumulative
    travel time, so they reflect the real speed on each part of the route.
    """
    cum = cumulative_distances(coords)
    poly_total = cum[-1] if cum and cum[-1] > 0 else 1.0
    scale = total_distance_miles / poly_total if total_distance_miles > 0 else 1.0
    cum = [d * scale for d in cum]
    if not coord_times or len(coord_times) != len(coords):
        coord_times = [0.0] * len(coords)

    def checkpoint(point, mile, seconds):
        return {
            'lat': round(point[1], 5),
            'lng': round(point[0], 5),
            'mile_marker': round(mile, 1),
            'eta': (departure_time + timedelta(seconds=seconds)).isoformat(),
        }

    checkpoints = [checkpoint(coords[0], 0.0, 0.0)]
    next_mile = interval
    for i in range(1, len(coords)):
        seg = cum[i] - cum[i - 1]
        while seg > 0 and next_mile <= cum[i] and next_mile < total_distance_miles:
            f = (next_mile - cum[i - 1]) / seg
            seconds = coord_times[i - 1] + (coord_times[i] - coord_times[i - 1]) * f
            checkpoints.append(checkpoint(interpolate_point(coords[i - 1], coords[i], f), next_mile, seconds))
            next_mile += interval
    checkpoints.append(checkpoint(coords[-1], total_distance_miles, coord_times[-1]))
    return checkpoints


def _format_duration(seconds):
    hours, rem = divmod(int(seconds), 3600)
    return f'{hours}h {rem // 60}m'


def get_routes_with_checkpoints(origin, destination, departure_time, interval='auto'):
    """Geocode, route and add ETA checkpoints.

    Returns (routes, meta) where meta has the provider, the interval used and any notices.
    """
    origin_coords = geocode(origin)
    dest_coords = geocode(destination)
    raw_routes, provider, notices = fetch_routes(origin_coords, dest_coords)

    miles = [r['distance_meters'] * METERS_TO_MILES for r in raw_routes]
    interval_miles, interval_notice = resolve_interval(interval, miles)
    if interval_notice:
        notices = notices + [interval_notice]   # copy: `notices` may be the cached list

    sides = side_labels([r['geometry'] for r in raw_routes], origin_coords, dest_coords)

    routes = []
    for i, (raw, distance_miles, side) in enumerate(zip(raw_routes, miles, sides)):
        roads = main_roads(raw['roads'], raw['distance_meters'])
        name = f'Route {i + 1}'
        if side:
            name += f' ({side})'
        if roads:
            name += f' via {" / ".join(roads)}'
        routes.append({
            'id': i + 1,
            'name': name,
            'main_roads': roads,
            'distance_miles': round(distance_miles, 1),
            'duration_seconds': int(raw['duration_seconds']),
            'duration_display': _format_duration(raw['duration_seconds']),
            'geometry': raw['geometry'],
            'checkpoints': generate_checkpoints(
                raw['geometry'], raw['coord_times'], distance_miles, departure_time, interval_miles,
            ),
            'checkpoint_interval_miles': interval_miles,
        })

    meta = {
        'provider': provider,
        'checkpoint_interval_miles': interval_miles,
        'notices': notices,
    }
    return routes, meta
