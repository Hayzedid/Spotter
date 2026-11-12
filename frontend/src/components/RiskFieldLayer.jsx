import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { useMap } from 'react-leaflet'
import { RISK_SCORE_RGB } from '../utils/riskColors'

/*
 * Continuous weather-risk field drawn on a canvas.
 *
 * Each screen cell takes an inverse-distance-weighted average of the risk
 * scores (0-4) at nearby grid points, so a colour always means a risk level:
 * points never stack the way density heatmaps do. The field fades out away
 * from the sample grid, i.e. outside the trip corridor.
 *
 * Interpolation weights depend only on the map view, so they're computed on
 * pan/zoom; changing the forecast hour only re-blends values on a small
 * offscreen image, which keeps the 0-48 h slider smooth.
 */

const CELL_PX = 6               // resolution of the interpolation grid
const INFLUENCE = 1.6           // influence radius, in grid spacings
const SOLID = 0.7               // fully opaque within this many spacings of a sample
const LOW_RISK_ALPHA = 0.5      // Low is drawn lighter so the base map stays readable

class RiskField extends L.Layer {
  constructor(options) {
    super()
    L.setOptions(this, options)
    this._points = []
    this._spacingMiles = 10
    this._values = []
    this._opacity = 0.7
    this._weights = null
  }

  onAdd(map) {
    if (!map.getPane('riskFieldPane')) {
      const pane = map.createPane('riskFieldPane')
      pane.style.zIndex = '350' // below route lines (overlayPane = 400)
      pane.style.pointerEvents = 'none'
    }
    this._canvas = L.DomUtil.create('canvas', 'risk-field-canvas')
    this._canvas.style.position = 'absolute'
    this._buffer = document.createElement('canvas')
    map.getPane('riskFieldPane').appendChild(this._canvas)
    map.on('moveend zoomend resize viewreset', this._reset, this)
    map.on('zoomstart', this._hide, this)
    this._reset()
  }

  onRemove(map) {
    L.DomUtil.remove(this._canvas)
    map.off('moveend zoomend resize viewreset', this._reset, this)
    map.off('zoomstart', this._hide, this)
  }

  setData(points, spacingMiles) {
    this._points = points || []
    this._spacingMiles = spacingMiles || 10
    if (this._map) this._reset()
  }

  setValues(values) {
    this._values = values || []
    if (this._map) this._redraw()
  }

  setOpacity(opacity) {
    this._opacity = opacity
    if (this._map) this._redraw()
  }

  _hide() {
    if (this._canvas) this._canvas.style.visibility = 'hidden'
  }

  _reset() {
    const map = this._map
    const size = map.getSize()
    L.DomUtil.setPosition(this._canvas, map.containerPointToLayerPoint([0, 0]))
    this._canvas.width = size.x
    this._canvas.height = size.y
    this._canvas.style.visibility = 'visible'
    this._computeWeights(size)
    this._redraw()
  }

  /** For every cell: the nearby sample points with their weights, and an edge-fade alpha. */
  _computeWeights(size) {
    const map = this._map
    const cols = Math.ceil(size.x / CELL_PX) + 1
    const rows = Math.ceil(size.y / CELL_PX) + 1
    const n = this._points.length
    this._weights = null
    if (n === 0) return

    const centre = map.getCenter()
    const a = map.latLngToContainerPoint(centre)
    const b = map.latLngToContainerPoint([centre.lat + 1 / 69, centre.lng])
    const spacingPx = Math.max(1, Math.abs(a.y - b.y) * this._spacingMiles)
    const radius = spacingPx * INFLUENCE
    const solid = spacingPx * SOLID
    const soft = spacingPx * 0.25

    // Bucket points by screen position so each cell only checks its neighbourhood
    const px = new Float32Array(n)
    const py = new Float32Array(n)
    const buckets = new Map()
    for (let i = 0; i < n; i++) {
      const p = map.latLngToContainerPoint(this._points[i])
      px[i] = p.x
      py[i] = p.y
      const key = `${Math.floor(p.x / radius)},${Math.floor(p.y / radius)}`
      if (!buckets.has(key)) buckets.set(key, [])
      buckets.get(key).push(i)
    }

    const start = new Int32Array(cols * rows + 1)
    const idx = []
    const wts = []
    const alpha = new Float32Array(cols * rows)
    for (let r = 0; r < rows; r++) {
      const cy = r * CELL_PX + CELL_PX / 2
      const by = Math.floor(cy / radius)
      for (let c = 0; c < cols; c++) {
        const cell = r * cols + c
        start[cell] = idx.length
        const cx = c * CELL_PX + CELL_PX / 2
        const bx = Math.floor(cx / radius)
        let nearest = Infinity
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const bucket = buckets.get(`${bx + dx},${by + dy}`)
            if (!bucket) continue
            for (const i of bucket) {
              const d = Math.hypot(px[i] - cx, py[i] - cy)
              if (d >= radius) continue
              if (d < nearest) nearest = d
              const taper = 1 - d / radius
              idx.push(i)
              wts.push((taper * taper) / (d * d + soft * soft))
            }
          }
        }
        alpha[cell] = nearest <= solid ? 1 : Math.max(0, 1 - (nearest - solid) / (radius - solid))
      }
    }
    start[cols * rows] = idx.length
    this._weights = { cols, rows, start, idx: Int32Array.from(idx), wts: Float32Array.from(wts), alpha }
  }

  _redraw() {
    const ctx = this._canvas.getContext('2d')
    ctx.clearRect(0, 0, this._canvas.width, this._canvas.height)
    const w = this._weights
    const values = this._values
    if (!w || !values || values.length === 0) return

    const { cols, rows, start, idx, wts, alpha } = w
    this._buffer.width = cols
    this._buffer.height = rows
    const bctx = this._buffer.getContext('2d')
    const image = bctx.createImageData(cols, rows)
    const data = image.data

    for (let cell = 0; cell < cols * rows; cell++) {
      if (alpha[cell] === 0) continue
      let sumW = 0
      let sumV = 0
      for (let k = start[cell]; k < start[cell + 1]; k++) {
        const v = values[idx[k]]
        if (v === null || v === undefined) continue
        sumW += wts[k]
        sumV += wts[k] * v
      }
      if (sumW === 0) continue
      const level = Math.min(4, Math.max(0, Math.round(sumV / sumW)))
      const [red, green, blue] = RISK_SCORE_RGB[level]
      const o = cell * 4
      data[o] = red
      data[o + 1] = green
      data[o + 2] = blue
      data[o + 3] = 255 * alpha[cell] * this._opacity * (level === 0 ? LOW_RISK_ALPHA : 1)
    }

    bctx.putImageData(image, 0, 0)
    ctx.imageSmoothingEnabled = true
    ctx.drawImage(this._buffer, 0, 0, cols * CELL_PX, rows * CELL_PX)
  }
}

export default function RiskFieldLayer({ points, spacingMiles, values, opacity = 0.7, visible = true }) {
  const map = useMap()
  const layerRef = useRef(null)

  if (!layerRef.current) layerRef.current = new RiskField()

  useEffect(() => {
    const layer = layerRef.current
    if (visible) layer.addTo(map)
    return () => {
      layer.remove()
    }
  }, [map, visible])

  useEffect(() => {
    layerRef.current.setData(points, spacingMiles)
  }, [points, spacingMiles])

  useEffect(() => {
    layerRef.current.setValues(values)
  }, [values])

  useEffect(() => {
    layerRef.current.setOpacity(opacity)
  }, [opacity])

  return null
}
