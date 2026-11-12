import { useState } from 'react'
import { ChevronDown, ChevronUp, CloudRain, ListFilter, Shield, Wind } from 'lucide-react'
import { RISK_UNKNOWN, riskToColor } from '../utils/riskColors'
import { formatDayTime } from '../utils/time'

// Precipitation in in/hr (the unit is in the column header), one line per type
function precipitation(weather) {
  if (!weather) return 'N/A'
  const lines = []
  if (weather.snow_in_hr > 0) lines.push(`${weather.snow_in_hr.toFixed(2)} snow`)
  if (weather.rain_in_hr > 0) lines.push(`${weather.rain_in_hr.toFixed(2)} rain`)
  if (!lines.length) return 'None'
  return lines.map((line) => <div key={line}>{line}</div>)
}

export default function CheckpointTable({ route }) {
  const [expanded, setExpanded] = useState(false)
  if (!route?.checkpoints?.length) return null

  return (
    <div className="checkpoint-table" onClick={(e) => e.stopPropagation()}>
      <button type="button" className="checkpoint-toggle" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        <span><ListFilter size={13} /> Checkpoints ({route.checkpoints.length})</span>
        <span>{expanded ? 'Hide' : 'View'} {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}</span>
      </button>

      {expanded && (
        <div className="checkpoint-scroll">
          <table>
            <thead>
              <tr>
                <th>Mile</th>
                <th>ETA</th>
                <th><Wind size={11} /> mph</th>
                <th><CloudRain size={11} /> in/hr</th>
                <th><Shield size={11} /> Risk</th>
              </tr>
            </thead>
            <tbody>
              {route.checkpoints.map((cp) => {
                const overall = cp.risk?.overall_risk || RISK_UNKNOWN
                const color = riskToColor(overall)
                return (
                  <tr key={cp.mile_marker}>
                    <td className="cell-strong">{cp.mile_marker}</td>
                    <td>{formatDayTime(cp.eta)}</td>
                    <td style={{ color: riskToColor(cp.risk?.wind_risk) }}>
                      {cp.weather ? cp.weather.wind_speed_mph : 'N/A'}
                    </td>
                    <td>{precipitation(cp.weather)}</td>
                    <td>
                      <span className="risk-pill" style={{ background: `${color}22`, color, borderColor: `${color}55` }}>
                        {overall}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
