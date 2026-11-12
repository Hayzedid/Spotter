import { AlertTriangle, CheckCircle2, Clock, HelpCircle, MapPin, Route, ShieldAlert } from 'lucide-react'
import { RISK_COLORS, RISK_ORDER, RISK_UNKNOWN } from '../utils/riskColors'
import CheckpointTable from './CheckpointTable'

// Most severe first for the mileage tags; the stacked bar runs Low -> No Travel
const TAG_ORDER = [...RISK_ORDER].reverse().concat(RISK_UNKNOWN)
const BAR_ORDER = [...RISK_ORDER, RISK_UNKNOWN]

const PROVIDER_LABELS = {
  'openrouteservice-hgv': 'Truck routing (OpenRouteService HGV)',
  'osrm-car': 'Car routing (OSRM): truck times will be longer',
}

function RiskBar({ riskMiles, totalMiles }) {
  return (
    <div className="risk-bar" aria-hidden="true">
      {BAR_ORDER.map((level) => {
        const miles = riskMiles[level] || 0
        if (miles <= 0) return null
        const pct = (miles / totalMiles) * 100
        return (
          <div key={level} title={`${level}: ${miles} mi (${Math.round(pct)}%)`}
            style={{ width: `${pct}%`, backgroundColor: RISK_COLORS[level] }} />
        )
      })}
    </div>
  )
}

export default function RouteSummary({ routes, meta, selectedRouteId, onSelectRoute }) {
  if (!routes || routes.length === 0) return null

  return (
    <div className="route-summary">
      <div className="summary-header">
        <h3>Route options ({routes.length})</h3>
        <span>Ranked safest first</span>
      </div>
      <div className="summary-meta">
        {PROVIDER_LABELS[meta?.provider] || meta?.provider}
      </div>

      {routes.map((route) => {
        const selected = route.id === selectedRouteId
        const summary = route.risk_summary || {}
        const riskMiles = summary.risk_miles || {}
        const totalMiles = summary.total_analyzed_miles || route.distance_miles || 1

        return (
          <div
            key={route.id}
            role="button"
            tabIndex={0}
            onClick={() => onSelectRoute(route.id)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelectRoute(route.id) }}
            className={`route-card ${route.recommended ? 'recommended' : ''} ${selected ? 'selected' : ''}`}
          >
            <div className="route-name">
              <span>
                <span className="route-rank">#{route.rank}</span> {route.name}
              </span>
              {route.recommended && (
                <span className="badge"><CheckCircle2 size={11} /> Recommended</span>
              )}
            </div>

            <div className="route-stats">
              <span><Route size={13} color="#2dd4bf" /> {route.distance_miles} mi</span>
              <span><Clock size={13} color="#2dd4bf" /> {route.duration_display}</span>
              <span><MapPin size={13} color="#2dd4bf" /> {route.checkpoints?.length || 0} checkpoints</span>
            </div>

            <div className="risk-profile">
              <div className="risk-profile-header">
                <span><ShieldAlert size={12} /> Risk profile</span>
                <span title="Mile-weighted average from 0 (Low) to 4 (No Travel)">
                  Avg risk {summary.avg_risk_score ?? 'N/A'} / 4
                </span>
              </div>
              <RiskBar riskMiles={riskMiles} totalMiles={totalMiles} />
              <div className="risk-tags">
                {TAG_ORDER.map((level) => {
                  const miles = riskMiles[level] || 0
                  if (miles === 0) return null
                  return (
                    <div key={level} className="risk-tag" style={{ borderColor: `${RISK_COLORS[level]}66` }}>
                      <span className="risk-dot" style={{ backgroundColor: RISK_COLORS[level] }} />
                      <span>{level}:</span>
                      <strong>{miles} mi</strong>
                    </div>
                  )
                })}
              </div>

              {summary.has_no_travel && (
                <div className="route-warning">
                  <AlertTriangle size={14} color="#ef4444" />
                  <span><strong>Warning:</strong> route crosses No Travel conditions</span>
                </div>
              )}
              {summary.has_unknown && (
                <div className="route-warning unknown">
                  <HelpCircle size={14} />
                  <span>Weather unavailable for part of this route; ranked below complete routes</span>
                </div>
              )}

              <CheckpointTable route={route} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
