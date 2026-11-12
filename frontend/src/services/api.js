import axios from 'axios'

// In development the Vite dev server proxies /api to Django (see vite.config.js).
// In production set VITE_API_BASE_URL to the backend origin, e.g. https://spotter-api.onrender.com
const baseURL = import.meta.env.VITE_API_BASE_URL
  ? `${import.meta.env.VITE_API_BASE_URL.replace(/\/$/, '')}/api`
  : '/api'

const client = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 60000,
})

export async function calculateRoutes({
  origin,
  destination,
  departure_time,
  load_weight,
  checkpoint_interval = 'auto',
  simulate_weather = false,
}) {
  const response = await client.post('/routes/', {
    origin,
    destination,
    departure_time,
    load_weight,
    checkpoint_interval,
    simulate_weather,
  })
  return response.data
}

/** Turn an axios error into one readable sentence (handles DRF field errors too). */
export function describeError(err) {
  const data = err.response?.data
  if (data?.error) return data.error
  if (data && typeof data === 'object') {
    const first = Object.entries(data)[0]
    if (first) {
      const [field, messages] = first
      const text = Array.isArray(messages) ? messages[0] : String(messages)
      return field === 'non_field_errors' ? text : `${field.replace(/_/g, ' ')}: ${text}`
    }
  }
  if (err.code === 'ECONNABORTED') return 'The request timed out. Please try again.'
  if (!err.response) return 'Cannot reach the Spotter API. Is the backend running?'
  return err.message || 'Failed to calculate routes'
}
