"""Simulated storm scenario for demos.

A single storm system moves along the trip axis over the 48 h window. Both the
route checkpoints (at their location and ETA) and the heatmap grid sample the
same field, so the map, popups and ranking always agree. The core is strong
enough to reach No Travel, and its mid-band winds (35-54 mph) make the load
rules visible.
"""
import math

from .geo import haversine, interpolate_point, offset_point, perpendicular_unit
from .corridor_service import HEATMAP_HOURS, heatmap_from_weather
from .weather_service import HOUR_FMT, nearest_hour, to_utc_naive


class StormField:
    START_FRACTION = 0.15      # storm centre position along origin->destination at departure
    END_FRACTION = 0.85        # ... and 48 h later
    LATERAL_FRACTION = 0.10    # centre offset to the left of the trip axis (as fraction of trip length)
    RADIUS_FRACTION = 0.22     # storm radius (as fraction of trip length)
    MIN_RADIUS_MILES = 8.0

    def __init__(self, origin, destination, departure_time):
        self.origin = origin
        self.destination = destination
        self.departure = to_utc_naive(departure_time)
        trip_miles = max(1.0, haversine(origin, destination))
        self.east, self.north = perpendicular_unit(origin, destination)
        self.lateral_miles = self.LATERAL_FRACTION * trip_miles
        self.radius = max(self.MIN_RADIUS_MILES, self.RADIUS_FRACTION * trip_miles)

    @classmethod
    def for_routes(cls, routes, departure_time):
        geom = routes[0]['geometry']
        return cls(geom[0], geom[-1], departure_time)

    def centre(self, when):
        hours = (to_utc_naive(when) - self.departure).total_seconds() / 3600.0
        t = min(1.0, max(0.0, hours / HEATMAP_HOURS))
        f = self.START_FRACTION + (self.END_FRACTION - self.START_FRACTION) * t
        on_axis = interpolate_point(self.origin, self.destination, f)
        return offset_point(on_axis, self.east * self.lateral_miles, self.north * self.lateral_miles)

    def weather(self, lat, lng, when):
        d = haversine([lng, lat], self.centre(when))
        s = math.exp(-((d / self.radius) ** 2))
        return {
            'wind_speed_mph': round(8.0 + 56.0 * s, 1),
            'rain_in_hr': round(max(0.0, 1.25 * s ** 1.5 - 0.03), 3),
            'snow_in_hr': round(max(0.0, 3.6 * s ** 2 - 0.3), 3),
            'forecast_time': nearest_hour(when).strftime(HOUR_FMT),
        }


def simulate_weather_for_routes(routes, field):
    for r in routes:
        r['checkpoints'] = [
            {**cp, 'weather': field.weather(cp['lat'], cp['lng'], nearest_hour(cp['eta']))}
            for cp in r['checkpoints']
        ]
    return routes


def simulate_corridor_heatmap(points, spacing, departure_time, load_weight, field):
    return heatmap_from_weather(
        points, spacing, departure_time, load_weight,
        weather_fn=lambda i, when: field.weather(points[i][0], points[i][1], when),
        horizon=None,
    )
