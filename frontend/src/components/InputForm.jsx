import { useState } from 'react'
import { AlertCircle, ArrowRight, Clock, CloudLightning, Compass, Gauge, MapPin, Navigation, Weight } from 'lucide-react'
import { toLocalInputValue } from '../utils/time'

const PRESETS = [
  { from: 'Chicago', to: 'Denver', origin: 'Chicago, IL', destination: 'Denver, CO', weight: 35000 },
  { from: 'Dallas', to: 'Houston', origin: 'Dallas, TX', destination: 'Houston, TX', weight: 45000 },
  { from: 'Baltimore', to: 'DC', origin: 'Baltimore, MD', destination: 'Washington, DC', weight: 25000 },
]
const WEIGHT_PRESETS = [25000, 35000, 45000]
const INTERVALS = [
  { value: 'auto', label: 'Auto' },
  { value: '10', label: '10 mi' },
  { value: '25', label: '25 mi' },
  { value: '50', label: '50 mi' },
]
const FORECAST_DAYS = 15 // keep departures comfortably inside Open-Meteo's 16-day range

function nextFullHour() {
  const d = new Date()
  d.setHours(d.getHours() + 1, 0, 0, 0)
  return d
}

export function defaultTrip() {
  return {
    origin: 'Chicago, IL',
    destination: 'Denver, CO',
    departureTime: toLocalInputValue(nextFullHour()),
    loadWeight: '35000',
    interval: 'auto',
    simulateWeather: false,
  }
}

/** Trip inputs. Collects values and hands them to `onSubmit`; the request itself is made by App. */
export default function InputForm({ initialValues, error, onSubmit }) {
  const [values, setValues] = useState(initialValues)
  const set = (field) => (value) => setValues((v) => ({ ...v, [field]: value }))

  const now = new Date()
  const minDeparture = toLocalInputValue(now)
  const maxDeparture = toLocalInputValue(new Date(now.getTime() + FORECAST_DAYS * 24 * 3600 * 1000))

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit({ ...values, origin: values.origin.trim(), destination: values.destination.trim() })
  }

  return (
    <div className="form-panel">
      {error && (
        <div className="error-banner" role="alert">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <div>
        <div className="section-label"><Compass size={12} /> Sample routes</div>
        <div className="chip-row">
          {PRESETS.map((p) => (
            <button
              key={p.from}
              type="button"
              className="chip"
              aria-label={`${p.from} to ${p.to}`}
              onClick={() => setValues((v) => ({
                ...v, origin: p.origin, destination: p.destination, loadWeight: String(p.weight),
              }))}
            >
              {p.from} <ArrowRight size={11} /> {p.to}
            </button>
          ))}
        </div>
      </div>

      <form className="input-form" onSubmit={handleSubmit}>
        <div className="form-row">
          <div className="form-group">
            <label htmlFor="origin"><MapPin size={12} color="#2dd4bf" /> Origin</label>
            <input id="origin" type="text" placeholder="e.g. Chicago, IL" value={values.origin}
              onChange={(e) => set('origin')(e.target.value)} required />
          </div>

          <div className="form-group">
            <label htmlFor="destination"><MapPin size={12} color="#f59e0b" /> Destination</label>
            <input id="destination" type="text" placeholder="e.g. Denver, CO" value={values.destination}
              onChange={(e) => set('destination')(e.target.value)} required />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label htmlFor="departure"><Clock size={12} /> Departure date and time</label>
            <input id="departure" type="datetime-local" value={values.departureTime} min={minDeparture} max={maxDeparture}
              onChange={(e) => set('departureTime')(e.target.value)} required />
            <span className="hint">Local time. Forecasts reach about {FORECAST_DAYS} days ahead.</span>
          </div>

          <div className="form-group">
            <div className="label-row">
              <label htmlFor="weight"><Weight size={12} /> Load weight (lb)</label>
              <div className="chip-row tight">
                {WEIGHT_PRESETS.map((w) => (
                  <button key={w} type="button"
                    className={`mini-chip ${values.loadWeight === String(w) ? 'active' : ''}`}
                    onClick={() => set('loadWeight')(String(w))}>
                    {w / 1000}k
                  </button>
                ))}
              </div>
            </div>
            <input id="weight" type="number" placeholder="e.g. 35000" value={values.loadWeight}
              onChange={(e) => set('loadWeight')(e.target.value)} min="0" max="200000" step="500" required />
            <span className="hint">
              Over 30,000 lb: 45-54 mph wind is No Travel. Over 40,000 lb: 35-44 mph wind is Severe.
            </span>
          </div>
        </div>

        <div className="form-group">
          <label><Gauge size={12} /> Weather sampling interval</label>
          <div className="segmented" role="radiogroup" aria-label="Weather sampling interval">
            {INTERVALS.map((opt) => (
              <button key={opt.value} type="button" role="radio" aria-checked={values.interval === opt.value}
                className={values.interval === opt.value ? 'active' : ''}
                onClick={() => set('interval')(opt.value)}>
                {opt.label}
              </button>
            ))}
          </div>
          <span className="hint">
            Auto: every 10 mi under 100 mi, 25 mi under 500 mi, otherwise 50 mi. A manual choice too coarse for
            the trip is tightened so storms between checkpoints aren't missed.
          </span>
        </div>

        <label className={`simulate-toggle ${values.simulateWeather ? 'active' : ''}`}>
          <input type="checkbox" checked={values.simulateWeather}
            onChange={(e) => set('simulateWeather')(e.target.checked)} />
          <CloudLightning size={14} />
          <span>Simulate a storm (demo of all risk levels)</span>
        </label>

        <button type="submit" className="submit-btn">
          <Navigation size={16} />
          <span>Calculate routes</span>
        </button>
      </form>
    </div>
  )
}
