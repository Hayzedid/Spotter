from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .services import route_service
from .services.corridor_service import build_corridor_grid, heatmap_from_weather
from .services.errors import RoutingInputError, UpstreamServiceError
from .services.geo import cumulative_distances, haversine
from .services.recommend_service import recommend_routes
from .services.risk_service import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MODERATE,
    RISK_NO_TRAVEL,
    RISK_SEVERE,
    RISK_UNKNOWN,
    calculate_risk_for_route,
    checkpoint_coverage,
    classify_checkpoint,
)
from .services.route_service import (
    _collect_routes,
    _parse_ors_feature,
    fetch_routes,
    generate_checkpoints,
    get_checkpoint_interval,
    main_roads,
    resolve_interval,
    shared_fraction,
    side_labels,
)
from .services.simulation_service import StormField, simulate_corridor_heatmap, simulate_weather_for_routes
from .services.weather_service import (
    fetch_weather_for_routes,
    forecast_horizon,
    nearest_hour,
    weather_at_hour,
)


def calm(wind=5.0, rain=0.0, snow=0.0):
    return {'wind_speed_mph': wind, 'rain_in_hr': rain, 'snow_in_hr': snow}


def straight_line(lng_start, lng_end, lat, n=50):
    return [[lng_start + (lng_end - lng_start) * i / (n - 1), lat] for i in range(n)]


class RiskServiceTests(TestCase):
    """Threshold classification, load-weight overrides, and per-route risk totals."""

    def test_wind_thresholds_light_load(self):
        cases = [
            (0.0, RISK_LOW), (24.9, RISK_LOW), (25.0, RISK_MODERATE), (34.9, RISK_MODERATE),
            (35.0, RISK_HIGH), (44.9, RISK_HIGH), (45.0, RISK_SEVERE), (54.9, RISK_SEVERE),
            (55.0, RISK_NO_TRAVEL), (70.0, RISK_NO_TRAVEL),
        ]
        for wind, expected in cases:
            with self.subTest(wind=wind):
                res = classify_checkpoint(calm(wind=wind), 20000)
                self.assertEqual(res['wind_risk'], expected)
                self.assertEqual(res['overall_risk'], expected)

    def test_load_weight_wind_overrides(self):
        self.assertEqual(classify_checkpoint(calm(wind=55.0), 0)['overall_risk'], RISK_NO_TRAVEL)
        self.assertEqual(classify_checkpoint(calm(wind=48.0), 30000)['overall_risk'], RISK_SEVERE)
        self.assertEqual(classify_checkpoint(calm(wind=48.0), 30001)['overall_risk'], RISK_NO_TRAVEL)
        self.assertEqual(classify_checkpoint(calm(wind=40.0), 40000)['overall_risk'], RISK_HIGH)
        self.assertEqual(classify_checkpoint(calm(wind=40.0), 40001)['overall_risk'], RISK_SEVERE)

    def test_rain_thresholds(self):
        cases = [
            (0.0, RISK_LOW), (0.09, RISK_LOW), (0.10, RISK_MODERATE), (0.24, RISK_MODERATE),
            (0.25, RISK_HIGH), (0.49, RISK_HIGH), (0.50, RISK_SEVERE), (1.00, RISK_SEVERE),
            (1.01, RISK_NO_TRAVEL),
        ]
        for rain, expected in cases:
            with self.subTest(rain=rain):
                res = classify_checkpoint(calm(rain=rain), 25000)
                self.assertEqual(res['rain_risk'], expected)
                self.assertEqual(res['overall_risk'], expected)

    def test_snow_thresholds(self):
        cases = [
            (0.0, RISK_LOW), (0.49, RISK_LOW), (0.50, RISK_MODERATE), (0.99, RISK_MODERATE),
            (1.00, RISK_HIGH), (1.99, RISK_HIGH), (2.00, RISK_SEVERE), (3.00, RISK_SEVERE),
            (3.01, RISK_NO_TRAVEL),
        ]
        for snow, expected in cases:
            with self.subTest(snow=snow):
                res = classify_checkpoint(calm(snow=snow), 25000)
                self.assertEqual(res['snow_risk'], expected)
                self.assertEqual(res['overall_risk'], expected)

    def test_worst_condition_dominates_overall_risk(self):
        res = classify_checkpoint(calm(wind=10.0, rain=0.30, snow=2.2), 25000)
        self.assertEqual((res['wind_risk'], res['rain_risk'], res['snow_risk']), (RISK_LOW, RISK_HIGH, RISK_SEVERE))
        self.assertEqual(res['overall_risk'], RISK_SEVERE)

    def test_missing_weather_is_unknown_not_low(self):
        res = classify_checkpoint(None, 35000)
        self.assertEqual(res['overall_risk'], RISK_UNKNOWN)
        self.assertIsNone(res['score'])

    def test_coverage_splits_at_midpoints_and_sums_to_route_length(self):
        cps = [{'mile_marker': m} for m in (0.0, 50.0, 100.0, 130.0)]
        self.assertEqual(checkpoint_coverage(cps), [25.0, 50.0, 40.0, 15.0])
        self.assertEqual(sum(checkpoint_coverage(cps)), 130.0)

    def test_route_risk_miles_and_weighted_average(self):
        checkpoints = [
            {'mile_marker': 0.0, 'weather': calm(wind=10)},     # Low, covers 25 mi
            {'mile_marker': 50.0, 'weather': calm(wind=38)},    # High, covers 50 mi
            {'mile_marker': 100.0, 'weather': calm(wind=50)},   # No Travel at 35k lb, covers 25 mi
        ]
        enriched, summary = calculate_risk_for_route(checkpoints, load_weight=35000)
        self.assertEqual([e['covered_miles'] for e in enriched], [25.0, 50.0, 25.0])
        self.assertEqual(summary['risk_miles'][RISK_LOW], 25.0)
        self.assertEqual(summary['risk_miles'][RISK_HIGH], 50.0)
        self.assertEqual(summary['risk_miles'][RISK_NO_TRAVEL], 25.0)
        self.assertEqual(summary['total_analyzed_miles'], 100.0)
        self.assertEqual(summary['avg_risk_score'], 2.0)   # (0*25 + 2*50 + 4*25) / 100
        self.assertEqual(summary['worst_risk'], RISK_NO_TRAVEL)
        self.assertTrue(summary['has_no_travel'])
        self.assertFalse(summary['has_unknown'])

    def test_unknown_checkpoints_are_excluded_from_average(self):
        checkpoints = [
            {'mile_marker': 0.0, 'weather': calm(wind=30)},     # Moderate, 25 mi
            {'mile_marker': 50.0, 'weather': None},             # Unknown, 50 mi
            {'mile_marker': 100.0, 'weather': calm(wind=30)},   # Moderate, 25 mi
        ]
        _, summary = calculate_risk_for_route(checkpoints, load_weight=20000)
        self.assertEqual(summary['risk_miles'][RISK_UNKNOWN], 50.0)
        self.assertEqual(summary['avg_risk_score'], 1.0)
        self.assertTrue(summary['has_unknown'])


class RecommendServiceTests(TestCase):
    """Ranking tie-breakers in priority order."""

    def _route(self, route_id, no_travel=0, severe=0, high=0, avg_risk=0.0, duration=3600, unknown=False):
        return {
            'id': route_id,
            'duration_seconds': duration,
            'risk_summary': {
                'risk_miles': {'No Travel': no_travel, 'Severe': severe, 'High': high},
                'avg_risk_score': avg_risk,
                'has_unknown': unknown,
            },
        }

    def _ids(self, *routes):
        return [r['id'] for r in recommend_routes(list(routes))]

    def test_prefers_fewest_severe_over_high_and_duration(self):
        ranked = recommend_routes([self._route(1, severe=10, avg_risk=0.5, duration=1800),
                                   self._route(2, high=50, avg_risk=1.5, duration=7200)])
        self.assertEqual([r['id'] for r in ranked], [2, 1])
        self.assertEqual([r['rank'] for r in ranked], [1, 2])
        self.assertEqual([r['recommended'] for r in ranked], [True, False])

    def test_prefers_fewest_high_when_severe_ties(self):
        self.assertEqual(self._ids(self._route(1, high=30, avg_risk=0.8, duration=2000),
                                   self._route(2, high=10, avg_risk=1.2, duration=4000)), [2, 1])

    def test_prefers_lowest_avg_risk_when_severe_and_high_tie(self):
        self.assertEqual(self._ids(self._route(1, avg_risk=1.4, duration=2000),
                                   self._route(2, avg_risk=0.4, duration=3000)), [2, 1])

    def test_small_avg_risk_difference_lets_travel_time_decide(self):
        # 0.04 vs 0.00 is within the 0.25 tolerance: the 3 h faster route wins
        self.assertEqual(self._ids(self._route(1, avg_risk=0.04, duration=19 * 3600),
                                   self._route(2, avg_risk=0.0, duration=22 * 3600)), [1, 2])

    def test_avg_risk_bands_are_taken_from_the_best_route(self):
        # 0.0 and 0.2 tie (fastest first); 0.4 is outside 0.0's band even though it's within 0.2's
        ids = self._ids(self._route(1, avg_risk=0.4, duration=1000),
                        self._route(2, avg_risk=0.2, duration=2000),
                        self._route(3, avg_risk=0.0, duration=3000))
        self.assertEqual(ids, [2, 3, 1])

    def test_prefers_shortest_travel_time_when_all_risks_tie(self):
        self.assertEqual(self._ids(self._route(1, avg_risk=0.5, duration=5400),
                                   self._route(2, avg_risk=0.5, duration=3600)), [2, 1])

    def test_no_travel_penalized_above_all(self):
        self.assertEqual(self._ids(self._route(1, no_travel=5, avg_risk=0.2, duration=1000),
                                   self._route(2, severe=25, avg_risk=1.5, duration=5000)), [2, 1])

    def test_routes_with_unknown_weather_rank_last(self):
        self.assertEqual(self._ids(self._route(1, unknown=True, duration=1000),
                                   self._route(2, severe=40, avg_risk=2.5, duration=9000)), [2, 1])


class RouteServiceTests(TestCase):
    """Checkpoint intervals, ETAs from per-segment travel time, road names, alternative selection."""

    def setUp(self):
        cache.clear()

    def test_checkpoint_interval_thresholds(self):
        for miles, expected in [(39.5, 10.0), (99.9, 10.0), (100.0, 25.0), (499.9, 25.0), (500.0, 50.0), (1200.0, 50.0)]:
            self.assertEqual(get_checkpoint_interval(miles), expected)

    def test_auto_interval_is_shared_and_based_on_longest_route(self):
        self.assertEqual(resolve_interval('auto', [495.0, 505.0, 498.0]), (50.0, None))
        self.assertEqual(resolve_interval('10', [495.0, 505.0]), (10.0, None))
        self.assertEqual(resolve_interval('50', [495.0, 505.0]), (50.0, None))

    def test_coarse_interval_steps_down_on_short_trips(self):
        # 49-mile trip at 50 mi would sample only start and end
        interval, notice = resolve_interval('50', [48.5, 49.1, 68.7])
        self.assertEqual(interval, 10.0)
        self.assertIn('every 10 mi instead of 50 mi', notice)
        # 150-mile trip: 50 gives 3 gaps -> 25 gives 6
        self.assertEqual(resolve_interval('50', [150.0])[0], 25.0)
        # Can't go below 10: a 20-mile trip stays at 10 without a notice
        self.assertEqual(resolve_interval('10', [20.0]), (10.0, None))

    def test_haversine_sanity(self):
        self.assertAlmostEqual(haversine([0.0, 40.0], [0.0, 41.0]), 69.1, delta=0.3)

    def test_checkpoint_etas_follow_per_segment_speed(self):
        # First degree of latitude driven at 30 mph, second at 69 mph
        coords = [[-87.6, 40.0], [-87.6, 41.0], [-87.6, 42.0]]
        d1 = haversine(coords[0], coords[1])
        d2 = haversine(coords[1], coords[2])
        times = [0.0, d1 / 30 * 3600, d1 / 30 * 3600 + d2 / 69 * 3600]
        dep = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)

        cps = generate_checkpoints(coords, times, d1 + d2, dep, 25.0)

        self.assertEqual([cp['mile_marker'] for cp in cps[:6]], [0.0, 25.0, 50.0, 75.0, 100.0, 125.0])
        eta_25 = datetime.fromisoformat(cps[1]['eta'])
        self.assertAlmostEqual((eta_25 - dep).total_seconds(), 25 / 30 * 3600, delta=1)
        eta_100 = datetime.fromisoformat(cps[4]['eta'])
        expected_100 = d1 / 30 * 3600 + (100 - d1) / 69 * 3600
        self.assertAlmostEqual((eta_100 - dep).total_seconds(), expected_100, delta=1)
        self.assertAlmostEqual(datetime.fromisoformat(cps[-1]['eta']).timestamp(), (dep + timedelta(seconds=times[-1])).timestamp(), delta=1)

    def test_mile_markers_use_provider_distance(self):
        coords = straight_line(-90.0, -89.0, 40.0)
        poly = cumulative_distances(coords)[-1]
        cps = generate_checkpoints(coords, [0.0] * len(coords), poly * 1.1, datetime.now(timezone.utc), 10.0)
        self.assertEqual(cps[-1]['mile_marker'], round(poly * 1.1, 1))
        self.assertTrue(all(b['mile_marker'] > a['mile_marker'] for a, b in zip(cps, cps[1:])))

    def test_ors_step_durations_give_non_uniform_times(self):
        coords = [[-90.0, 40.0], [-89.5, 40.0], [-89.0, 40.0]]
        feature = {
            'geometry': {'coordinates': coords},
            'properties': {
                'summary': {'distance': 85000, 'duration': 3000},
                'segments': [{'steps': [
                    {'way_points': [0, 1], 'duration': 2000, 'distance': 42500, 'name': 'Main Street'},
                    {'way_points': [1, 2], 'duration': 1000, 'distance': 42500, 'name': 'I 80 Express'},
                    {'way_points': [2, 2], 'duration': 0, 'distance': 0, 'name': '-'},
                ]}],
            },
        }
        parsed = _parse_ors_feature(feature)
        for actual, expected in zip(parsed['coord_times'], [0.0, 2000.0, 3000.0]):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertEqual(list(parsed['roads']), ['I-80'])

    def test_main_roads_prefers_interstates_in_driving_order(self):
        roads = {}
        for name, dist in [('Ronald Reagan Memorial Tollway, I 88, IL 110', 140), ('US 6', 300),
                           ('I 80 Express', 356), ('I 80', 119), ('I 76', 180), ('-', 385)]:
            route_service._add_road(roads, name, dist)
        self.assertEqual(roads['I-80'], 475)
        # Of a 1000-unit route: I-80 (47.5%), US-6 (30%) qualify; I-76 (18%) and I-88 (14%) don't
        self.assertEqual(main_roads(roads, 1000), ['US-6', 'I-80'])
        self.assertEqual(main_roads(roads, 5000), [])   # nothing covers 25% of a long route

    def test_side_labels_follow_geometry(self):
        origin, dest = [-100.0, 40.0], [-90.0, 40.0]   # eastbound trip
        north = straight_line(-100.0, -90.0, 41.0)
        middle = straight_line(-100.0, -90.0, 40.0)
        south = straight_line(-100.0, -90.0, 39.0)
        self.assertEqual(side_labels([south, north, middle], origin, dest), ['Southern', 'Northern', 'Central'])
        # Westbound: left of travel is south, labels must still be geographic
        self.assertEqual(side_labels([north, south], dest, origin), ['Northern', 'Southern'])
        # North-south trip
        east = [[-89.0, 35.0 + i * 0.1] for i in range(50)]
        west = [[-91.0, 35.0 + i * 0.1] for i in range(50)]
        self.assertEqual(side_labels([east, west], [-90.0, 35.0], [-90.0, 40.0]), ['Eastern', 'Western'])
        # Near-identical routes get no side label
        self.assertEqual(side_labels([middle, middle], origin, dest), [None, None])

    def test_shared_fraction(self):
        a = straight_line(-90.0, -89.0, 40.0)
        self.assertEqual(shared_fraction(a, a), 1.0)
        self.assertEqual(shared_fraction(a, straight_line(-90.0, -89.0, 41.0)), 0.0)

    def _fake(self, lat, duration):
        geom = straight_line(-90.0, -89.0, lat)
        return {'geometry': geom, 'duration_seconds': duration, 'distance_meters': 90000,
                'coord_times': [0.0] * len(geom), 'roads': {}}

    def test_alternatives_must_be_distinct_and_reasonable(self):
        origin, dest = [-90.0, 40.0], [-89.0, 40.0]
        main = self._fake(40.0, 3600)
        detours = route_service.detour_waypoints(origin, dest)
        by_detour = {
            tuple(detours[0]): self._fake(40.0, 3700),   # duplicate of main -> rejected
            tuple(detours[1]): self._fake(40.5, 9000),   # > 1.6x slower -> rejected
            tuple(detours[2]): self._fake(40.5, 4000),   # accepted
            tuple(detours[3]): self._fake(39.5, 4200),   # accepted
        }
        requested = []

        def route_fn(waypoints, alternatives=False):
            if len(waypoints) == 2:
                return [main]
            requested.append(tuple(waypoints[1]))
            return [by_detour[tuple(waypoints[1])]]

        routes = _collect_routes(route_fn, origin, dest, use_builtin_alternatives=False)
        self.assertEqual([r['duration_seconds'] for r in routes], [3600, 4000, 4200])
        self.assertEqual(len(requested), 4)   # stops after the second pair

    @override_settings(ORS_API_KEY='test-key')
    def test_ors_failure_falls_back_to_osrm_with_notice(self):
        routes = [self._fake(40.0, 3600), self._fake(40.5, 4000), self._fake(39.5, 4200)]
        with patch.object(route_service, '_ors_directions', side_effect=UpstreamServiceError('quota')), \
             patch.object(route_service, '_osrm_route', side_effect=[routes, [], []]):
            result, provider, notices = fetch_routes([-90.0, 40.0], [-89.0, 40.0])
        self.assertEqual(provider, route_service.PROVIDER_OSRM_CAR)
        self.assertEqual(len(result), 3)
        self.assertTrue(any('car estimates' in n for n in notices))

    def _response(self, status, payload):
        class Resp:
            status_code = status
            text = str(payload)
            def json(self):
                return payload
            def raise_for_status(self):
                if status >= 400:
                    raise route_service.requests.HTTPError(str(status))
        return Resp()

    @override_settings(ORS_API_KEY='test-key')
    def test_router_error_classification(self):
        # ORS over its 6,000 km limit -> treated as unavailable so OSRM gets a try
        with patch.object(route_service.requests, 'post', return_value=self._response(400, {'error': {'code': 2004}})):
            with self.assertRaises(UpstreamServiceError):
                route_service._ors_directions([[0, 0], [1, 1]])
        # ORS "no route" / "unroutable point" -> simply no route
        for code in (2009, 2010):
            with patch.object(route_service.requests, 'post', return_value=self._response(400, {'error': {'code': code}})):
                self.assertEqual(route_service._ors_directions([[0, 0], [1, 1]]), [])
        # OSRM "NoRoute" -> no route, not an outage
        with patch.object(route_service.requests, 'get', return_value=self._response(400, {'code': 'NoRoute'})):
            self.assertEqual(route_service._osrm_route([[0, 0], [1, 1]]), [])
        # Real OSRM outage -> upstream error
        with patch.object(route_service.requests, 'get', return_value=self._response(503, {})):
            with self.assertRaises(UpstreamServiceError):
                route_service._osrm_route([[0, 0], [1, 1]])

    @override_settings(ORS_API_KEY='test-key')
    def test_places_on_different_continents_give_input_error(self):
        # e.g. a misspelled origin matched in South Africa, destination in Texas
        with patch.object(route_service, '_ors_directions', side_effect=UpstreamServiceError('2004')), \
             patch.object(route_service, '_osrm_route', return_value=[]):
            with self.assertRaises(RoutingInputError) as ctx:
                fetch_routes([18.48, -33.57], [-95.37, 29.76])
        self.assertIn('Check the place names', str(ctx.exception))

    def test_unroutable_detour_is_skipped_not_fatal(self):
        main = self._fake(40.0, 3600)

        def route_fn(waypoints, alternatives=False):
            if len(waypoints) == 2:
                return [main]
            raise RoutingInputError('detour not routable')

        routes = _collect_routes(route_fn, [-90.0, 40.0], [-89.0, 40.0], use_builtin_alternatives=False)
        self.assertEqual(len(routes), 1)

    def test_no_route_is_an_input_error(self):
        with self.assertRaises(RoutingInputError):
            _collect_routes(lambda w, alternatives=False: [], [-90.0, 40.0], [-89.0, 40.0], False)


class WeatherServiceTests(TestCase):
    """Forecast-hour matching and handling of missing data."""

    def test_nearest_hour_rounds(self):
        self.assertEqual(nearest_hour('2026-11-10T08:29:00+00:00'), datetime(2026, 11, 10, 8))
        self.assertEqual(nearest_hour('2026-11-10T08:31:00+00:00'), datetime(2026, 11, 10, 9))

    def test_weather_at_hour_returns_none_when_missing(self):
        series = {'2026-11-10T08:00': {'wind_speed_mph': 12.0, 'rain_in_hr': None, 'snow_in_hr': 0.0}}
        self.assertIsNone(weather_at_hour(series, '2026-11-10T08:00:00Z'))   # incomplete values
        self.assertIsNone(weather_at_hour(series, '2026-11-12T08:00:00Z'))   # hour not in window
        self.assertIsNone(weather_at_hour(None, '2026-11-10T08:00:00Z'))     # request failed

    def test_failed_lookup_marks_checkpoints_unknown(self):
        routes = [{'checkpoints': [
            {'lat': 40.0, 'lng': -90.0, 'mile_marker': 0.0, 'eta': '2026-11-10T08:00:00+00:00'},
            {'lat': 40.0, 'lng': -89.0, 'mile_marker': 53.0, 'eta': '2026-11-10T09:00:00+00:00'},
        ]}]
        with patch('routing.services.weather_service.fetch_hourly', return_value=[None, None]):
            fetch_weather_for_routes(routes)
        _, summary = calculate_risk_for_route(routes[0]['checkpoints'], 30000)
        self.assertTrue(summary['has_unknown'])
        self.assertEqual(summary['risk_miles'][RISK_LOW], 0.0)

    def test_forecast_horizon_is_sixteen_days(self):
        self.assertEqual(forecast_horizon(datetime(2026, 11, 11, 18, 0)), datetime(2026, 11, 26, 23, 0))


class CorridorAndSimulationTests(TestCase):
    """Corridor grid coverage and the shared simulated storm field."""

    def _route(self, lat, departure, route_id):
        geom = straight_line(-100.0, -90.0, lat, n=200)
        miles = cumulative_distances(geom)[-1]
        times = [d / 60.0 * 3600 for d in cumulative_distances(geom)]   # 60 mph
        return {
            'id': route_id,
            'name': f'Route {route_id}',
            'geometry': geom,
            'distance_miles': miles,
            'duration_seconds': times[-1],
            'checkpoints': generate_checkpoints(geom, times, miles, departure, 25.0),
        }

    def test_corridor_grid_covers_route_with_lateral_points(self):
        dep = datetime(2026, 11, 10, 8, tzinfo=timezone.utc)
        grid, spacing = build_corridor_grid([self._route(40.0, dep, 1)])
        lngs = [p[1] for p in grid]
        lats = [p[0] for p in grid]
        self.assertLessEqual(len(grid), 180)
        self.assertLess(min(lngs), -99.8)
        self.assertGreater(max(lngs), -90.2)
        self.assertGreater(max(lats), 40.05)   # rows either side of the road
        self.assertLess(min(lats), 39.95)

    def test_heatmap_marks_frames_beyond_forecast_unavailable(self):
        dep = datetime(2026, 11, 10, 8)
        hm = heatmap_from_weather([(40.0, -90.0)], 10.0, dep, 30000,
                                  weather_fn=lambda i, when: calm(), horizon=dep + timedelta(hours=10))
        self.assertEqual(len(hm['hours']), 49)
        self.assertTrue(hm['hours'][10]['available'])
        self.assertFalse(hm['hours'][11]['available'])
        self.assertEqual(hm['hours'][0]['risk'], [0])

    def test_simulated_checkpoints_and_heatmap_sample_the_same_storm(self):
        dep = datetime(2026, 11, 10, 8, tzinfo=timezone.utc)
        routes = [self._route(40.0, dep, 1)]
        field = StormField.for_routes(routes, dep)
        simulate_weather_for_routes(routes, field)
        cp = routes[0]['checkpoints'][3]
        grid = [(cp['lat'], cp['lng'])]
        hm = simulate_corridor_heatmap(grid, 10.0, dep, 35000, field)
        offset = int((nearest_hour(cp['eta']) - nearest_hour(dep)).total_seconds() // 3600)
        cp_score = classify_checkpoint(cp['weather'], 35000)['score']
        self.assertEqual(hm['hours'][offset]['risk'][0], cp_score)

    def test_simulated_storm_reaches_no_travel_and_route_avoiding_it_wins(self):
        dep = datetime(2026, 11, 10, 8, tzinfo=timezone.utc)
        # The storm sits ~10% of the trip length north of the axis; route 1 drives through it
        stormy = self._route(40.75, dep, 1)
        clear = self._route(38.6, dep, 2)
        field = StormField([-100.0, 40.0], [-90.0, 40.0], dep)
        self.assertEqual(classify_checkpoint(field.weather(*reversed(field.centre(dep)), dep), 0)['overall_risk'],
                         RISK_NO_TRAVEL)

        simulate_weather_for_routes([stormy, clear], field)
        for r in (stormy, clear):
            r['checkpoints'], r['risk_summary'] = calculate_risk_for_route(r['checkpoints'], 35000)
        ranked = recommend_routes([stormy, clear])
        self.assertEqual(ranked[0]['id'], 2)
        self.assertGreater(stormy['risk_summary']['avg_risk_score'], clear['risk_summary']['avg_risk_score'])

    def test_simulated_storm_responds_to_load_weight(self):
        dep = datetime(2026, 11, 10, 8, tzinfo=timezone.utc)
        route = self._route(40.75, dep, 1)
        simulate_weather_for_routes([route], StormField([-100.0, 40.0], [-90.0, 40.0], dep))
        _, light = calculate_risk_for_route(route['checkpoints'], 25000)
        _, heavy = calculate_risk_for_route(route['checkpoints'], 45000)
        self.assertGreater(heavy['avg_risk_score'], light['avg_risk_score'])


class CalculateRoutesViewTests(TestCase):
    """POST /api/routes/ validation, error mapping, and end-to-end mocked recommendation."""

    def setUp(self):
        self.client = APIClient()
        self.dep = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)

    def _payload(self, **overrides):
        payload = {'origin': 'Chicago, IL', 'destination': 'Rockford, IL',
                   'departure_time': self.dep.isoformat(), 'load_weight': 45000}
        payload.update(overrides)
        return payload

    def test_health_check_endpoints(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        resp = self.client.get('/api/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {'status': 'ok'})

    def test_validation_errors(self):
        self.assertEqual(self.client.post('/api/routes/', {'origin': 'Chicago, IL'}, format='json').status_code, 400)
        cases = {
            'negative weight': {'load_weight': -500},
            'past departure': {'departure_time': (self.dep - timedelta(days=2)).isoformat()},
            'beyond forecast': {'departure_time': (self.dep + timedelta(days=20)).isoformat()},
            'bad interval': {'checkpoint_interval': '15'},
        }
        for label, override in cases.items():
            with self.subTest(label):
                self.assertEqual(self.client.post('/api/routes/', self._payload(**override), format='json').status_code, 400)

    @patch('routing.views.get_routes_with_checkpoints', side_effect=RoutingInputError("Could not find a location named 'Atlantis'."))
    def test_unknown_location_is_400_with_message(self, _):
        resp = self.client.post('/api/routes/', self._payload(origin='Atlantis'), format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Atlantis', resp.data['error'])

    @patch('routing.views.get_routes_with_checkpoints', side_effect=UpstreamServiceError('OSRM down'))
    def test_upstream_failure_is_502(self, _):
        self.assertEqual(self.client.post('/api/routes/', self._payload(), format='json').status_code, 502)

    def _mock_routes(self, eta_offset_hours=0):
        def cp(lat, lng, mile, hours):
            return {'lat': lat, 'lng': lng, 'mile_marker': mile,
                    'eta': (self.dep + timedelta(hours=hours + eta_offset_hours)).isoformat()}
        return [
            {'id': 1, 'name': 'Route 1', 'distance_miles': 120.0, 'duration_seconds': 7200,
             'geometry': [[-87.6, 41.8], [-88.6, 41.8]],
             'checkpoints': [cp(41.8, -87.6, 0.0, 0), cp(41.8, -88.1, 60.0, 1), cp(41.8, -88.6, 120.0, 2)]},
            {'id': 2, 'name': 'Route 2', 'distance_miles': 150.0, 'duration_seconds': 10800,
             'geometry': [[-87.6, 41.8], [-88.6, 41.5]],
             'checkpoints': [cp(41.8, -87.6, 0.0, 0), cp(41.6, -88.1, 75.0, 1.5), cp(41.5, -88.6, 150.0, 3)]},
        ], {'provider': 'test', 'checkpoint_interval_miles': 50.0, 'notices': []}

    @patch('routing.views.fetch_corridor_heatmap')
    @patch('routing.views.fetch_weather_for_routes')
    @patch('routing.views.get_routes_with_checkpoints')
    def test_load_weight_shifts_recommended_route(self, mock_routes, mock_weather, mock_heatmap):
        mock_routes.return_value = self._mock_routes()

        def fake_weather(routes):
            for r in routes:   # route 1 (faster) has 40 mph wind, route 2 is calm
                wind = 40.0 if r['id'] == 1 else 10.0
                r['checkpoints'] = [{**cp, 'weather': calm(wind=wind)} for cp in r['checkpoints']]
            return routes

        mock_weather.side_effect = fake_weather
        mock_heatmap.return_value = {'points': [], 'hours': []}

        heavy = self.client.post('/api/routes/', self._payload(load_weight=45000), format='json')
        self.assertEqual(heavy.status_code, 200)
        self.assertEqual([r['id'] for r in heavy.data['routes']], [2, 1])   # 40 mph at >40k lb is Severe
        self.assertEqual(heavy.data['routes'][1]['risk_summary']['risk_miles']['Severe'], 120.0)

        mock_routes.return_value = self._mock_routes()
        light = self.client.post('/api/routes/', self._payload(load_weight=30000), format='json')
        self.assertEqual([r['id'] for r in light.data['routes']], [2, 1])   # still High miles vs none
        self.assertEqual(light.data['routes'][1]['risk_summary']['risk_miles']['High'], 120.0)

    @patch('routing.views.get_routes_with_checkpoints')
    def test_trip_ending_after_forecast_is_rejected(self, mock_routes):
        hours_left = (forecast_horizon() - self.dep.replace(tzinfo=None)).total_seconds() / 3600
        mock_routes.return_value = self._mock_routes(eta_offset_hours=hours_left)
        resp = self.client.post('/api/routes/', self._payload(), format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('forecast', resp.data['error'])
