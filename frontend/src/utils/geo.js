const EARTH_RADIUS_MILES = 3958.8

/** Great-circle distance in miles between two [lng, lat] points. */
export function haversine([lng1, lat1], [lng2, lat2]) {
  const toRad = Math.PI / 180
  const a = Math.sin(((lat2 - lat1) * toRad) / 2) ** 2
    + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(((lng2 - lng1) * toRad) / 2) ** 2
  return 2 * EARTH_RADIUS_MILES * Math.asin(Math.sqrt(Math.min(1, a)))
}

/**
 * Cumulative mile marker at each geometry point, scaled so the last one equals
 * the route's reported distance (the same convention as the backend's checkpoints).
 */
export function cumulativeMiles(geometry, totalMiles) {
  const cum = [0]
  for (let i = 1; i < geometry.length; i++) cum.push(cum[i - 1] + haversine(geometry[i - 1], geometry[i]))
  const last = cum[cum.length - 1]
  const scale = totalMiles > 0 && last > 0 ? totalMiles / last : 1
  return cum.map((d) => d * scale)
}

/** [lat, lng] at a given mile along a route (binary search on cumulative miles). */
export function pointAtMile(geometry, cum, mile) {
  if (mile <= 0) return [geometry[0][1], geometry[0][0]]
  const n = cum.length
  if (mile >= cum[n - 1]) return [geometry[n - 1][1], geometry[n - 1][0]]
  let lo = 0
  let hi = n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (cum[mid] <= mile) lo = mid
    else hi = mid
  }
  const span = cum[hi] - cum[lo]
  const f = span > 0 ? (mile - cum[lo]) / span : 0
  return [
    geometry[lo][1] + (geometry[hi][1] - geometry[lo][1]) * f,
    geometry[lo][0] + (geometry[hi][0] - geometry[lo][0]) * f,
  ]
}

/**
 * Where a truck is at time `t` (ms), from its checkpoints' ETAs.
 * Returns { mile, status: 'departing' | 'en-route' | 'arrived', checkpointIndex }, where
 * checkpointIndex is the checkpoint whose stretch (halfway to each neighbour) contains the truck.
 */
export function truckProgress(checkpoints, t) {
  const etas = checkpoints.map((cp) => new Date(cp.eta).getTime())
  const last = checkpoints.length - 1
  if (t <= etas[0]) return { mile: 0, status: 'departing', checkpointIndex: 0 }
  if (t >= etas[last]) return { mile: checkpoints[last].mile_marker, status: 'arrived', checkpointIndex: last }

  let i = 0
  while (i < last - 1 && etas[i + 1] <= t) i++
  const span = etas[i + 1] - etas[i]
  const f = span > 0 ? (t - etas[i]) / span : 0
  const mile = checkpoints[i].mile_marker + (checkpoints[i + 1].mile_marker - checkpoints[i].mile_marker) * f
  const midpoint = (checkpoints[i].mile_marker + checkpoints[i + 1].mile_marker) / 2
  return { mile, status: 'en-route', checkpointIndex: mile < midpoint ? i : i + 1 }
}
