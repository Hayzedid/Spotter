import { useCallback, useState } from 'react'
import { Clock, Info, Loader2, MapPinned, Route } from 'lucide-react'
import BrandMark from './components/BrandMark'
import InputForm, { defaultTrip } from './components/InputForm'
import Modal from './components/Modal'
import RouteMap from './components/RouteMap'
import RouteSummary from './components/RouteSummary'
import TripSummary from './components/TripSummary'
import { calculateRoutes, describeError } from './services/api'
import './App.css'

function App() {
  const [result, setResult] = useState(null)
  const [trip, setTrip] = useState(null)              // the trip shown in the results
  const [draft, setDraft] = useState(defaultTrip)     // what the form opens with
  const [modalOpen, setModalOpen] = useState(false)
  const [selectedRouteId, setSelectedRouteId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const openForm = useCallback(() => setModalOpen(true), [])
  const closeForm = useCallback(() => {
    setModalOpen(false)
    setError(null)
  }, [])

  const handleSubmit = async (values) => {
    // Close straight away; the map shows the loading state. Reopen with the error if it fails.
    setDraft(values)
    setModalOpen(false)
    setError(null)
    setLoading(true)
    try {
      const data = await calculateRoutes({
        origin: values.origin,
        destination: values.destination,
        // datetime-local is parsed as local time, then sent as UTC
        departure_time: new Date(values.departureTime).toISOString(),
        load_weight: parseFloat(values.loadWeight) || 0,
        checkpoint_interval: values.interval,
        simulate_weather: values.simulateWeather,
      })
      setResult(data)
      setTrip(values)
      const recommended = data.routes.find((r) => r.recommended) || data.routes[0]
      setSelectedRouteId(recommended ? recommended.id : null)
    } catch (err) {
      setError(describeError(err))
      setModalOpen(true)
    } finally {
      setLoading(false)
    }
  }

  const routes = result?.routes || null
  const notices = result?.meta?.notices || []

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-icon"><BrandMark size={22} /></div>
          <div>
            <h1>Spotter Weather-Aware Truck Routing</h1>
            <span className="brand-subtitle">Compare routes by weather risk, load weight and travel time</span>
          </div>
        </div>
        <span className="header-pill"><Clock size={12} /> 48-hour forecast</span>
      </header>

      <div className="app-layout">
        <aside className="sidebar">
          {loading && !routes && (
            <div className="sidebar-empty">
              <Loader2 size={28} className="spin" />
              <p>Calculating routes and weather</p>
            </div>
          )}

          {!loading && !routes && (
            <div className="sidebar-empty">
              <MapPinned size={36} />
              <h2>Plan a trip</h2>
              <p>
                Enter an origin, destination, departure time and load weight to compare three truck routes
                by weather risk and travel time.
              </p>
              <button type="button" className="submit-btn" onClick={openForm}>
                <Route size={16} /> Plan a trip
              </button>
            </div>
          )}

          {routes && trip && (
            <>
              <TripSummary trip={trip} meta={result.meta} onEdit={openForm} />
              {notices.map((notice) => (
                <div key={notice} className="notice-banner">
                  <Info size={15} />
                  <span>{notice}</span>
                </div>
              ))}
              <RouteSummary
                routes={routes}
                meta={result.meta}
                selectedRouteId={selectedRouteId}
                onSelectRoute={setSelectedRouteId}
              />
            </>
          )}
        </aside>

        <main className="map-container">
          {loading && (
            <div className="loading-overlay">
              <div className="loading-title"><Loader2 size={20} color="#2dd4bf" className="spin" /> Calculating routes and weather</div>
              <div className="loading-subtitle">Truck routing, forecasts at each checkpoint ETA, and the 48 h corridor forecast</div>
            </div>
          )}
          <RouteMap
            routes={routes}
            heatmap={result?.heatmap}
            selectedRouteId={selectedRouteId}
            onSelectRoute={setSelectedRouteId}
          />
        </main>
      </div>

      {modalOpen && (
        <Modal title="Plan a trip" icon={Route} onClose={closeForm}>
          <InputForm initialValues={draft} error={error} onSubmit={handleSubmit} />
        </Modal>
      )}
    </div>
  )
}

export default App
