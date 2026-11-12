import { Fragment, useMemo } from 'react'
import L from 'leaflet'
import { CircleMarker, Marker, Pane, Tooltip } from 'react-leaflet'
import { cumulativeMiles, pointAtMile, truckProgress } from '../utils/geo'
import { RISK_UNKNOWN, riskToColor } from '../utils/riskColors'
import { formatDayTime } from '../utils/time'

// Lucide "truck" glyph, inlined so the marker needs no extra rendering
const TRUCK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/></svg>'

function truckIcon(selected, arrived) {
  return L.divIcon({
    className: '',
    html: `<div class="truck-marker${selected ? ' selected' : ''}${arrived ? ' arrived' : ''}">${TRUCK_SVG}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  })
}

const ICONS = {
  'false-false': truckIcon(false, false),
  'true-false': truckIcon(true, false),
  'false-true': truckIcon(false, true),
  'true-true': truckIcon(true, true),
}

function statusText(route, progress) {
  const arrival = route.checkpoints[route.checkpoints.length - 1].eta
  if (progress.status === 'arrived') return `Arrived ${formatDayTime(arrival)}`
  if (progress.status === 'departing') return 'Departing'
  return `Mile ${Math.round(progress.mile)} of ${route.distance_miles}, arrives ${formatDayTime(arrival)}`
}

/**
 * Each truck's position at the forecast slider's hour, plus a ring on the
 * checkpoint whose stretch it is driving, so the checkpoint's colour (weather
 * at arrival) can be compared with the heatmap at the same moment.
 */
export default function TruckMarkers({ routes, time, selectedRouteId }) {
  const cumById = useMemo(() => {
    const out = {}
    for (const r of routes || []) out[r.id] = cumulativeMiles(r.geometry, r.distance_miles)
    return out
  }, [routes])

  if (!routes?.length || !time) return null
  const t = new Date(`${time}:00Z`).getTime()

  return (
    <Pane name="truckPane" style={{ zIndex: 450 }}>
      {routes.map((route) => {
        if (!route.checkpoints?.length || !route.geometry?.length) return null
        const selected = route.id === selectedRouteId
        const progress = truckProgress(route.checkpoints, t)
        const position = pointAtMile(route.geometry, cumById[route.id], progress.mile)
        const cp = route.checkpoints[progress.checkpointIndex]
        const arrived = progress.status === 'arrived'

        return (
          <Fragment key={route.id}>
            {!arrived && (
              <CircleMarker
                pane="truckPane"
                center={[cp.lat, cp.lng]}
                radius={selected ? 13 : 10}
                interactive={false}
                pathOptions={{
                  color: riskToColor(cp.risk?.overall_risk || RISK_UNKNOWN),
                  weight: 3,
                  fill: false,
                  dashArray: selected ? null : '3, 3',
                }}
              />
            )}
            {/* keyed on selection: a tooltip's `permanent` option can't change after creation */}
            <Marker
              key={`truck-${selected}`}
              position={position}
              icon={ICONS[`${selected}-${arrived}`]}
              zIndexOffset={selected ? 1000 : 0}
            >
              <Tooltip direction="top" offset={[0, -12]} permanent={selected} className="truck-tooltip">
                <strong>{route.name}</strong>
                <br />
                {statusText(route, progress)}
              </Tooltip>
            </Marker>
          </Fragment>
        )
      })}
    </Pane>
  )
}
