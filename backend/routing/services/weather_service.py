"""Hourly forecasts from Open-Meteo.

Missing data is reported as `None`, never as zeros: a failed lookup must not
read as calm weather (and therefore "Low" risk).
"""
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
FORECAST_DAYS = 16              # Open-Meteo's maximum forecast range (today + 15 days)
BATCH_SIZE = 50                 # locations per request (keeps URLs well under length limits)
MAX_PARALLEL_REQUESTS = 4
WEATHER_CACHE_SECONDS = 30 * 60
HOUR_FMT = '%Y-%m-%dT%H:00'


def to_utc_naive(dt):
    """Accept an aware/naive datetime or ISO string; return a naive UTC datetime."""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def nearest_hour(dt):
    dt = to_utc_naive(dt)
    return (dt + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def forecast_horizon(now=None):
    """Last forecast hour Open-Meteo can serve (naive UTC)."""
    now = to_utc_naive(now or datetime.now(timezone.utc))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(days=FORECAST_DAYS) - timedelta(hours=1)


def fetch_hourly(points, start, end):
    """Hourly wind/rain/snow for each (lat, lng) between `start` and `end` (inclusive).

    Returns a list aligned with `points`; each entry maps 'YYYY-MM-DDTHH:00' to
    {'wind_speed_mph', 'rain_in_hr', 'snow_in_hr'} (values may be None), or is
    None if that point's batch failed. The window is clamped to the forecast horizon.
    """
    if not points:
        return []
    start = to_utc_naive(start).replace(minute=0, second=0, microsecond=0)
    end = min(to_utc_naive(end), forecast_horizon())
    if end < start:
        return [None] * len(points)

    batches = [points[i:i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
        results = list(pool.map(lambda b: _fetch_batch(b, start, end), batches))
    return [entry for batch in results for entry in batch]


def _fetch_batch(batch, start, end):
    params = {
        'latitude': ','.join(f'{p[0]:.4f}' for p in batch),
        'longitude': ','.join(f'{p[1]:.4f}' for p in batch),
        'hourly': 'wind_speed_10m,rain,snowfall',
        'wind_speed_unit': 'mph',
        'precipitation_unit': 'inch',
        'start_hour': start.strftime('%Y-%m-%dT%H:%M'),
        'end_hour': end.strftime('%Y-%m-%dT%H:%M'),
        'timezone': 'UTC',
    }
    key = 'weather:' + hashlib.sha1(repr(sorted(params.items())).encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('Open-Meteo request failed for %d points: %s', len(batch), exc)
        return [None] * len(batch)

    locations = data if isinstance(data, list) else [data]
    parsed = []
    for idx in range(len(batch)):
        if idx >= len(locations):
            parsed.append(None)
            continue
        hourly = locations[idx].get('hourly', {})
        winds = hourly.get('wind_speed_10m', [])
        rains = hourly.get('rain', [])
        snows = hourly.get('snowfall', [])
        series = {}
        for i, t in enumerate(hourly.get('time', [])):
            series[t] = {
                'wind_speed_mph': winds[i] if i < len(winds) else None,
                'rain_in_hr': rains[i] if i < len(rains) else None,
                'snow_in_hr': snows[i] if i < len(snows) else None,
            }
        parsed.append(series)
    cache.set(key, parsed, WEATHER_CACHE_SECONDS)
    return parsed


def weather_at_hour(series, when):
    """Weather dict for the forecast hour nearest `when`, or None if unavailable."""
    if not series:
        return None
    hour = nearest_hour(when).strftime(HOUR_FMT)
    values = series.get(hour)
    if not values or any(values[k] is None for k in ('wind_speed_mph', 'rain_in_hr', 'snow_in_hr')):
        return None
    return {
        'wind_speed_mph': round(values['wind_speed_mph'], 1),
        'rain_in_hr': round(values['rain_in_hr'], 3),
        'snow_in_hr': round(values['snow_in_hr'], 3),
        'forecast_time': hour,
    }


def fetch_weather_for_routes(routes):
    """Attach `weather` (dict or None) to every checkpoint of every route, in one batched lookup."""
    all_cps = [cp for r in routes for cp in r['checkpoints']]
    if not all_cps:
        return routes

    unique = list(dict.fromkeys((cp['lat'], cp['lng']) for cp in all_cps))
    etas = [nearest_hour(cp['eta']) for cp in all_cps]
    series_list = fetch_hourly(unique, min(etas), max(etas))
    by_point = dict(zip(unique, series_list))

    for r in routes:
        r['checkpoints'] = [
            {**cp, 'weather': weather_at_hour(by_point.get((cp['lat'], cp['lng'])), cp['eta'])}
            for cp in r['checkpoints']
        ]
    return routes
