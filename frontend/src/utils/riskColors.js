export const RISK_LEVELS = {
  LOW: 'Low',
  MODERATE: 'Moderate',
  HIGH: 'High',
  SEVERE: 'Severe',
  NO_TRAVEL: 'No Travel',
}

export const RISK_UNKNOWN = 'Unknown'

// Index = risk score from the API (0 = Low ... 4 = No Travel)
export const RISK_ORDER = [
  RISK_LEVELS.LOW,
  RISK_LEVELS.MODERATE,
  RISK_LEVELS.HIGH,
  RISK_LEVELS.SEVERE,
  RISK_LEVELS.NO_TRAVEL,
]

export const RISK_COLORS = {
  [RISK_LEVELS.LOW]: '#22c55e',
  [RISK_LEVELS.MODERATE]: '#facc15',
  [RISK_LEVELS.HIGH]: '#f97316',
  [RISK_LEVELS.SEVERE]: '#dc2626',
  [RISK_LEVELS.NO_TRAVEL]: '#a855f7',
  [RISK_UNKNOWN]: '#64748b',
}

const POPUP_LABEL_COLORS = {
  [RISK_LEVELS.LOW]: '#15803d',
  [RISK_LEVELS.MODERATE]: '#a16207',
  [RISK_LEVELS.HIGH]: '#c2410c',
  [RISK_LEVELS.SEVERE]: '#b91c1c',
  [RISK_LEVELS.NO_TRAVEL]: '#7e22ce',
  [RISK_UNKNOWN]: '#475569',
}

export function riskToColor(level) {
  return RISK_COLORS[level] || RISK_COLORS[RISK_UNKNOWN]
}

export function riskToPopupLabelColor(level) {
  return POPUP_LABEL_COLORS[level] || POPUP_LABEL_COLORS[RISK_UNKNOWN]
}

export function riskToBadgeTextColor(level) {
  return level === RISK_LEVELS.MODERATE ? '#0f172a' : '#ffffff'
}

/** [r, g, b] for each risk score, used by the canvas risk field. */
export const RISK_SCORE_RGB = RISK_ORDER.map((level) => {
  const hex = RISK_COLORS[level]
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
})
