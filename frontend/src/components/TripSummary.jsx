import { ArrowRight, Clock, CloudLightning, Gauge, Pencil, Weight } from 'lucide-react'

function formatDeparture(localValue) {
  return new Date(localValue).toLocaleString([], {
    weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

/** The searched trip at the top of the results, with a button to edit it. */
export default function TripSummary({ trip, meta, onEdit }) {
  const intervalUsed = meta?.checkpoint_interval_miles
  const intervalLabel = trip.interval === 'auto'
    ? `Auto (every ${intervalUsed} mi)`
    : `Every ${intervalUsed ?? trip.interval} mi`

  return (
    <div className="trip-summary">
      <div className="trip-route">
        <span>{trip.origin}</span>
        <ArrowRight size={14} className="trip-arrow" />
        <span>{trip.destination}</span>
      </div>
      <div className="trip-details">
        <span><Clock size={12} /> {formatDeparture(trip.departureTime)}</span>
        <span><Weight size={12} /> {Number(trip.loadWeight).toLocaleString()} lb</span>
        <span><Gauge size={12} /> {intervalLabel}</span>
        {trip.simulateWeather && <span className="trip-tag"><CloudLightning size={12} /> Simulated storm</span>}
      </div>
      <button type="button" className="edit-trip-btn" onClick={onEdit}>
        <Pencil size={13} /> Edit trip
      </button>
    </div>
  )
}
