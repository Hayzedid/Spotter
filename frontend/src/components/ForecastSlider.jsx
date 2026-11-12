import { useEffect, useState } from 'react'
import { CloudRain, Layers, Pause, Play, RotateCcw, Shield, Snowflake, Wind } from 'lucide-react'
import { formatUtcHour } from '../utils/time'

const PLAYBACK_MS = 500
const METRICS = [
  { id: 'risk', label: 'Overall', Icon: Shield },
  { id: 'wind', label: 'Wind', Icon: Wind },
  { id: 'rain', label: 'Rain', Icon: CloudRain },
  { id: 'snow', label: 'Snow', Icon: Snowflake },
]
const TICKS = [0, 6, 12, 18, 24, 30, 36, 42, 48]

export default function ForecastSlider({
  hours,
  currentHour,
  onChangeHour,
  metric,
  onChangeMetric,
  visible,
  onToggleVisible,
  opacity,
  onChangeOpacity,
}) {
  const [isPlaying, setIsPlaying] = useState(false)
  const maxHour = Math.max(0, hours.length - 1)
  const frame = hours[currentHour] || hours[0]

  useEffect(() => {
    if (!isPlaying) return undefined
    const timer = setInterval(() => {
      onChangeHour((prev) => {
        if (prev >= maxHour) {
          setIsPlaying(false)
          return prev
        }
        return prev + 1
      })
    }, PLAYBACK_MS)
    return () => clearInterval(timer)
  }, [isPlaying, maxHour, onChangeHour])

  return (
    <div className="forecast-slider">
      <div className="slider-toolbar">
        <div className="slider-group">
          <button
            type="button"
            className={`slider-play ${isPlaying ? 'playing' : ''}`}
            onClick={() => {
              if (!isPlaying && currentHour >= maxHour) onChangeHour(0)
              setIsPlaying(!isPlaying)
            }}
          >
            {isPlaying ? <Pause size={13} /> : <Play size={13} />}
            <span>{isPlaying ? 'Pause' : 'Play'}</span>
          </button>
          <button
            type="button"
            className="slider-reset"
            title="Back to departure time"
            onClick={() => {
              setIsPlaying(false)
              onChangeHour(0)
            }}
          >
            <RotateCcw size={12} />
            <span>Reset</span>
          </button>
          <div>
            <div className="slider-hour">{currentHour === 0 ? 'Departure' : `Departure +${currentHour}h`}</div>
            <div className="slider-time">
              {formatUtcHour(frame?.time)}
              {frame && !frame.available && <span className="slider-unavailable"> (forecast not available)</span>}
            </div>
          </div>
        </div>

        <div className="slider-group" role="group" aria-label="Heatmap layer">
          {METRICS.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              className={`metric-btn ${metric === id ? 'active' : ''}`}
              onClick={() => onChangeMetric(id)}
              aria-pressed={metric === id}
            >
              <Icon size={12} />
              <span>{label}</span>
            </button>
          ))}
        </div>

        <div className="slider-group">
          <label className="heatmap-toggle">
            <Layers size={13} color="#2dd4bf" />
            <input type="checkbox" checked={visible} onChange={(e) => onToggleVisible(e.target.checked)} />
            <span>Heatmap</span>
          </label>
          {visible && (
            <input
              type="range"
              min="0.2"
              max="1"
              step="0.05"
              value={opacity}
              onChange={(e) => onChangeOpacity(parseFloat(e.target.value))}
              aria-label="Heatmap opacity"
              title={`Opacity: ${Math.round(opacity * 100)}%`}
              className="opacity-range"
            />
          )}
        </div>
      </div>

      <input
        type="range"
        min="0"
        max={maxHour}
        step="1"
        value={currentHour}
        onChange={(e) => {
          setIsPlaying(false)
          onChangeHour(parseInt(e.target.value, 10))
        }}
        aria-label="Forecast hour"
        className="hour-range"
      />
      <div className="slider-ticks">
        {TICKS.filter((t) => t <= maxHour).map((t) => (
          <span key={t}>{t === 0 ? '0h' : `+${t}h`}</span>
        ))}
      </div>
    </div>
  )
}
