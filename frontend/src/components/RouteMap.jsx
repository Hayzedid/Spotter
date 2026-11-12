import { useEffect, useMemo, useState } from 'react'
import { MapContainer, TileLayer } from 'react-leaflet'
import { Shield } from 'lucide-react'
import { RISK_COLORS, RISK_ORDER, RISK_UNKNOWN } from '../utils/riskColors'
import RouteLayers from './RouteLayers'
import RiskFieldLayer from './RiskFieldLayer'
import ForecastSlider from './ForecastSlider'
import TruckMarkers from './TruckMarkers'
import 'leaflet/dist/leaflet.css'

const METRIC_TITLES = {
  risk: 'Overall risk',
  wind: 'Wind risk',
  rain: 'Rain risk',
  snow: 'Snow risk',
}

export default function RouteMap({ routes, heatmap, selectedRouteId, onSelectRoute }) {
  const [currentHour, setCurrentHour] = useState(0)
  const [metric, setMetric] = useState('risk')
  const [fieldVisible, setFieldVisible] = useState(true)
  const [fieldOpacity, setFieldOpacity] = useState(0.7)

  useEffect(() => {
    setCurrentHour(0)
  }, [heatmap])

  const frame = heatmap?.hours?.[currentHour]
  const values = useMemo(() => (frame?.available ? frame[metric] : null), [frame, metric])
  const hasUnknown = routes?.some((r) => r.risk_summary?.has_unknown)

  return (
    <div className="map-wrapper">
      <MapContainer center={[39.8283, -98.5795]} zoom={4} className="leaflet-map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {heatmap?.points?.length > 0 && (
          <RiskFieldLayer
            points={heatmap.points}
            spacingMiles={heatmap.spacing_miles}
            values={values}
            opacity={fieldOpacity}
            visible={fieldVisible}
          />
        )}
        <RouteLayers routes={routes} selectedRouteId={selectedRouteId} onSelectRoute={onSelectRoute} />
        <TruckMarkers routes={routes} time={frame?.time} selectedRouteId={selectedRouteId} />
      </MapContainer>

      {heatmap?.hours?.length > 0 && (
        <ForecastSlider
          hours={heatmap.hours}
          currentHour={currentHour}
          onChangeHour={setCurrentHour}
          metric={metric}
          onChangeMetric={setMetric}
          visible={fieldVisible}
          onToggleVisible={setFieldVisible}
          opacity={fieldOpacity}
          onChangeOpacity={setFieldOpacity}
        />
      )}

      <div className="map-legend">
        <div className="legend-title">
          <Shield size={12} />
          <span>{METRIC_TITLES[metric]}</span>
        </div>
        {[...RISK_ORDER, ...(hasUnknown ? [RISK_UNKNOWN] : [])].map((label) => (
          <div key={label} className="legend-row">
            <span className="legend-swatch" style={{ backgroundColor: RISK_COLORS[label] }} />
            <span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
