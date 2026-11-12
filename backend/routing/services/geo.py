"""Small geometry helpers shared by the routing, corridor and simulation services.

Coordinates are [lng, lat] lists (GeoJSON order) unless a name says otherwise.
"""
import math

EARTH_RADIUS_MILES = 3958.8


def haversine(coord1, coord2):
    """Great-circle distance in miles between two [lng, lat] coordinates."""
    lng1, lat1 = math.radians(coord1[0]), math.radians(coord1[1])
    lng2, lat2 = math.radians(coord2[0]), math.radians(coord2[1])
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def interpolate_point(coord1, coord2, fraction):
    """Linear interpolation between two [lng, lat] coordinates."""
    return [
        coord1[0] + (coord2[0] - coord1[0]) * fraction,
        coord1[1] + (coord2[1] - coord1[1]) * fraction,
    ]


def cumulative_distances(coords):
    """Running distance in miles at each coordinate of a polyline (first entry is 0)."""
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine(coords[i - 1], coords[i]))
    return cum


def miles_per_degree_lng(lat):
    return 69.172 * math.cos(math.radians(lat))


def offset_point(coord, east_miles, north_miles):
    """Move a [lng, lat] point by a distance in miles east and north."""
    lat = coord[1] + north_miles / 69.0
    lng = coord[0] + east_miles / max(1e-6, miles_per_degree_lng(coord[1]))
    return [lng, lat]


def perpendicular_unit(start, end):
    """Unit vector (east, north) in miles-space perpendicular (left-hand) to start->end."""
    mid_lat = (start[1] + end[1]) / 2
    dx = (end[0] - start[0]) * miles_per_degree_lng(mid_lat)
    dy = (end[1] - start[1]) * 69.0
    length = math.hypot(dx, dy) or 1.0
    return -dy / length, dx / length
