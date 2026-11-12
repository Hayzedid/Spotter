import { Fragment, memo, useEffect, useMemo } from 'react'
import { CircleMarker, Polyline, Popup, useMap } from 'react-leaflet'
import { Clock, CloudRain, Shield, Snowflake, Wind } from 'lucide-react'
import { RISK_UNKNOWN, riskToBadgeTextColor, riskToColor, riskToPopupLabelColor } from '../utils/riskColors'
import { formatDayTime } from '../utils/time'
import { cumulativeMiles } from '../utils/geo'

/**
 * Split a route into coloured pieces. Each checkpoint's risk covers the road
 * halfway to its neighbours (the same rule the backend uses for risk miles).
 */
export function buildRiskSegments(geometry, checkpoints, totalMiles) {
  if (!geometry || geometry.length < 2) return []
  const riskOf = (cp) => cp?.risk?.overall_risk || RISK_UNKNOWN
  if (!checkpoints || checkpoints.length < 2) {
    return [{ positions: geometry.map(([lng, lat]) => [lat, lng]), risk: riskOf(checkpoints?.[0]) }]
  }

  const cum = cumulativeMiles(geometry, totalMiles)
  const boundaries = checkpoints.slice(0, -1).map((cp, i) => (cp.mile_marker + checkpoints[i + 1].mile_marker) / 2)

  const segments = []
  let k = 0
  let current = { positions: [[geometry[0][1], geometry[0][0]]], risk: riskOf(checkpoints[0]) }
  for (let i = 1; i < geometry.length; i++) {
    const m0 = cum[i - 1]
    const m1 = cum[i]
    while (k < boundaries.length && boundaries[k] <= m1) {
      const f = m1 > m0 ? (boundaries[k] - m0) / (m1 - m0) : 0
      const split = [
        geometry[i - 1][1] + (geometry[i][1] - geometry[i - 1][1]) * f,
        geometry[i - 1][0] + (geometry[i][0] - geometry[i - 1][0]) * f,
      ]
      current.positions.push(split)
      k += 1
      const nextRisk = riskOf(checkpoints[k])
      if (nextRisk !== current.risk) {
        segments.push(current)
        current = { positions: [split], risk: nextRisk }
      }
    }
    current.positions.push([geometry[i][1], geometry[i][0]])
  }
  segments.push(current)
  return segments
}

function FitBounds({ routes }) {
  const map = useMap()
  useEffect(() => {
    const points = routes.flatMap((r) => (r.geometry || []).map(([lng, lat]) => [lat, lng]))
    // Extra room at the bottom and right for the forecast slider and legend overlays
    if (points.length > 0) map.fitBounds(points, { paddingTopLeft: [40, 40], paddingBottomRight: [170, 170] })
  }, [routes, map])
  return null
}

function WeatherRow({ Icon, iconColor, label, value, unit, risk }) {
  return (
    <div className="popup-row">
      <span className="popup-label"><Icon size={12} color={iconColor} /> {label}:</span>
      <span>
        <strong>{value ?? 'N/A'}{value !== undefined && value !== null ? ` ${unit}` : ''}</strong>{' '}
        <span style={{ color: riskToPopupLabelColor(risk), fontWeight: 600 }}>({risk})</span>
      </span>
    </div>
  )
}

function CheckpointPopup({ route, cp }) {
  const level = cp.risk?.overall_risk || RISK_UNKNOWN
  const w = cp.weather
  return (
    <Popup>
      <div className="checkpoint-popup">
        <div className="popup-title">{route.name}</div>
        <div className="popup-mile">Mile {cp.mile_marker}</div>
        <div className="popup-eta"><Clock size={11} /> Arrival: {formatDayTime(cp.eta)}</div>
        {w ? (
          <div className="popup-weather">
            <WeatherRow Icon={Wind} iconColor="#0d9488" label="Wind" value={w.wind_speed_mph} unit="mph" risk={cp.risk?.wind_risk} />
            <WeatherRow Icon={CloudRain} iconColor="#0d9488" label="Rain" value={w.rain_in_hr} unit="in/hr" risk={cp.risk?.rain_risk} />
            <WeatherRow Icon={Snowflake} iconColor="#6366f1" label="Snow" value={w.snow_in_hr} unit="in/hr" risk={cp.risk?.snow_risk} />
          </div>
        ) : (
          <div className="popup-weather popup-missing">Weather data unavailable for this checkpoint.</div>
        )}
        <div className="popup-badge" style={{ background: riskToColor(level), color: riskToBadgeTextColor(level) }}>
          <Shield size={12} /> Risk: {level.toUpperCase()}
        </div>
      </div>
    </Popup>
  )
}

/** Route lines and checkpoint markers. Memoised so forecast-slider changes don't re-render them. */
function RouteLayers({ routes, selectedRouteId, onSelectRoute }) {
  const segmentsById = useMemo(() => {
    const out = {}
    for (const r of routes || []) out[r.id] = buildRiskSegments(r.geometry, r.checkpoints, r.distance_miles)
    return out
  }, [routes])

  if (!routes || routes.length === 0) return null

  const isSelected = (r) => r.id === selectedRouteId
  // Draw the selected route last so it sits on top
  const ordered = [...routes].sort((a, b) => Number(isSelected(a)) - Number(isSelected(b)))

  return (
    <>
      {ordered.map((route) => {
        const selected = isSelected(route)
        const select = () => onSelectRoute(route.id)
        return (
          <Fragment key={route.id}>
            {segmentsById[route.id].map((seg, i) => (
              <Polyline
                key={`seg-${i}-${selected}`}
                positions={seg.positions}
                pathOptions={{
                  color: riskToColor(seg.risk),
                  weight: selected ? 6 : 3.5,
                  opacity: selected ? 0.95 : 0.6,
                  dashArray: selected ? null : '8, 6',
                }}
                eventHandlers={{ click: select }}
              />
            ))}
            {route.checkpoints.map((cp, i) => (
              <CircleMarker
                key={`cp-${i}-${selected}`}
                center={[cp.lat, cp.lng]}
                radius={selected ? 7 : 5}
                pathOptions={{
                  fillColor: riskToColor(cp.risk?.overall_risk),
                  color: '#071e24',
                  weight: selected ? 2 : 1.5,
                  fillOpacity: selected ? 1 : 0.85,
                }}
                eventHandlers={{ click: select }}
              >
                <CheckpointPopup route={route} cp={cp} />
              </CircleMarker>
            ))}
          </Fragment>
        )
      })}
      <FitBounds routes={routes} />
    </>
  )
}

export default memo(RouteLayers)
