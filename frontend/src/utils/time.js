/** Value for an <input type="datetime-local"> in the user's local time zone. */
export function toLocalInputValue(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** "Wed 3:40 PM" style label in local time, from an ISO string. */
export function formatDayTime(iso) {
  if (!iso) return 'N/A'
  return new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })
}

/** "Wed, Nov 12, 3:00 PM" in local time, from an API hour string ('YYYY-MM-DDTHH:00', UTC). */
export function formatUtcHour(hour) {
  if (!hour) return ''
  return new Date(`${hour}:00Z`).toLocaleString([], {
    weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}
