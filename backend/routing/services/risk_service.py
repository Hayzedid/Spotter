"""Risk classification (assessment thresholds + load rules) and per-route risk totals."""

RISK_LOW = 'Low'
RISK_MODERATE = 'Moderate'
RISK_HIGH = 'High'
RISK_SEVERE = 'Severe'
RISK_NO_TRAVEL = 'No Travel'
RISK_UNKNOWN = 'Unknown'   # weather data unavailable for this checkpoint

RISK_ORDER = [RISK_LOW, RISK_MODERATE, RISK_HIGH, RISK_SEVERE, RISK_NO_TRAVEL]
RISK_SCORES = {level: i for i, level in enumerate(RISK_ORDER)}


def classify_wind(wind_mph, load_weight):
    """Wind thresholds with the load rules applied.

    <25 Low | 25-34 Moderate | 35-44 High | 45-54 Severe | >=55 No Travel
    Load rules: >=55 mph is No Travel for any load; 45-54 mph with >30,000 lb is
    No Travel; 35-44 mph with >40,000 lb is Severe.
    """
    if wind_mph >= 55.0:
        return RISK_NO_TRAVEL
    if wind_mph >= 45.0:
        return RISK_NO_TRAVEL if load_weight > 30000 else RISK_SEVERE
    if wind_mph >= 35.0:
        return RISK_SEVERE if load_weight > 40000 else RISK_HIGH
    if wind_mph >= 25.0:
        return RISK_MODERATE
    return RISK_LOW


def classify_rain(rain_in_hr):
    """<0.10 Low | 0.10-0.25 Moderate | 0.25-0.50 High | 0.50-1.00 Severe | >1.00 No Travel.

    A value exactly on a shared boundary (0.25, 0.50) takes the higher class.
    """
    if rain_in_hr > 1.00:
        return RISK_NO_TRAVEL
    if rain_in_hr >= 0.50:
        return RISK_SEVERE
    if rain_in_hr >= 0.25:
        return RISK_HIGH
    if rain_in_hr >= 0.10:
        return RISK_MODERATE
    return RISK_LOW


def classify_snow(snow_in_hr):
    """<0.5 Low | 0.5-1.0 Moderate | 1.0-2.0 High | 2.0-3.0 Severe | >3.0 No Travel."""
    if snow_in_hr > 3.0:
        return RISK_NO_TRAVEL
    if snow_in_hr >= 2.0:
        return RISK_SEVERE
    if snow_in_hr >= 1.0:
        return RISK_HIGH
    if snow_in_hr >= 0.5:
        return RISK_MODERATE
    return RISK_LOW


def worst_risk(*levels):
    return max(levels, key=lambda level: RISK_SCORES[level])


def classify_checkpoint(weather, load_weight):
    """Per-condition and overall risk for one checkpoint. `weather=None` gives Unknown."""
    if weather is None:
        return {
            'wind_risk': RISK_UNKNOWN,
            'rain_risk': RISK_UNKNOWN,
            'snow_risk': RISK_UNKNOWN,
            'overall_risk': RISK_UNKNOWN,
            'score': None,
        }
    wind_risk = classify_wind(weather.get('wind_speed_mph', 0.0), load_weight)
    rain_risk = classify_rain(weather.get('rain_in_hr', 0.0))
    snow_risk = classify_snow(weather.get('snow_in_hr', 0.0))
    overall = worst_risk(wind_risk, rain_risk, snow_risk)
    return {
        'wind_risk': wind_risk,
        'rain_risk': rain_risk,
        'snow_risk': snow_risk,
        'overall_risk': overall,
        'score': RISK_SCORES[overall],
    }


def checkpoint_coverage(checkpoints):
    """Miles of road each checkpoint represents: half the gap to each neighbour.

    The first and last checkpoints cover half a gap; coverage sums to the route length.
    """
    markers = [cp.get('mile_marker', 0.0) for cp in checkpoints]
    n = len(markers)
    if n < 2:
        return [0.0] * n
    coverage = []
    for i in range(n):
        left = (markers[i] - markers[i - 1]) / 2 if i > 0 else 0.0
        right = (markers[i + 1] - markers[i]) / 2 if i < n - 1 else 0.0
        coverage.append(max(0.0, left) + max(0.0, right))
    return coverage


def calculate_risk_for_route(checkpoints, load_weight):
    """Classify each checkpoint and total the route's miles per risk level.

    `avg_risk_score` is the mile-weighted mean score (0 = Low ... 4 = No Travel)
    over checkpoints with known weather.
    """
    coverage = checkpoint_coverage(checkpoints)
    risk_miles = {level: 0.0 for level in RISK_ORDER + [RISK_UNKNOWN]}
    enriched = []
    weighted_score = 0.0
    known_miles = 0.0
    worst_score = None

    for cp, miles in zip(checkpoints, coverage):
        risk = classify_checkpoint(cp.get('weather'), load_weight)
        enriched.append({**cp, 'risk': risk, 'covered_miles': round(miles, 1)})
        risk_miles[risk['overall_risk']] += miles
        if risk['score'] is not None:
            weighted_score += risk['score'] * miles
            known_miles += miles
            worst_score = risk['score'] if worst_score is None else max(worst_score, risk['score'])

    summary = {
        'risk_miles': {k: round(v, 1) for k, v in risk_miles.items()},
        'total_analyzed_miles': round(sum(coverage), 1),
        'avg_risk_score': round(weighted_score / known_miles, 2) if known_miles > 0 else None,
        'worst_risk': RISK_ORDER[worst_score] if worst_score is not None else RISK_UNKNOWN,
        'has_no_travel': risk_miles[RISK_NO_TRAVEL] > 0,
        'has_unknown': any(e['risk']['score'] is None for e in enriched),
    }
    return enriched, summary
