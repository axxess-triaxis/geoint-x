import type { Band, CaseStatus, Transition } from './types'

// Fixed categorical slots (reference palette, light-mode steps). Colour follows the
// transition class everywhere: map, legend, charts and backend change masks.
// Green (slot 6) is deliberately unused: on a land-change map it reads as "gain".
export const TRANSITIONS: { id: Transition; label: string; short: string; color: string }[] = [
  { id: 'water_gain', label: 'Non-water to water', short: 'Water gain', color: '#2a78d6' },
  { id: 'water_loss', label: 'Water to non-water', short: 'Water loss', color: '#eb6834' },
  { id: 'revegetation', label: 'Bare to vegetation', short: 'Revegetation', color: '#1baf7a' },
  { id: 'cropland_to_bare_or_built', label: 'Cropland to bare/built-up', short: 'Cropland loss', color: '#eda100' },
  { id: 'wetland_vegetation_loss', label: 'Wetland vegetation loss', short: 'Wetland veg. loss', color: '#e87ba4' },
  { id: 'vegetation_to_bare_or_built', label: 'Vegetation to bare/built-up', short: 'Vegetation loss', color: '#4a3aa7' },
  { id: 'forest_clearing', label: 'Tree cover to bare/built-up', short: 'Tree cover loss', color: '#e34948' },
]
export const T = Object.fromEntries(TRANSITIONS.map((t) => [t.id, t])) as Record<
  Transition,
  (typeof TRANSITIONS)[number]
>

// Status palette: reserved, always paired with a text label.
export const BAND: Record<Band, { color: string; label: string }> = {
  P1: { color: '#d03b3b', label: 'P1 high' },
  P2: { color: '#ec835a', label: 'P2 medium' },
  P3: { color: '#fab219', label: 'P3 low' },
}

export const STATUS: Record<CaseStatus, { label: string; tone: string }> = {
  UNVERIFIED: { label: 'Unverified', tone: 'neutral' },
  UNDER_REVIEW: { label: 'Under review', tone: 'info' },
  CONFIRMED: { label: 'Confirmed', tone: 'good' },
  REJECTED: { label: 'Rejected', tone: 'muted' },
}

export const POLYGON_KIND: Record<string, { label: string; color: string }> = {
  wetland: { label: 'Wetland', color: '#2a78d6' },
  protected_area: { label: 'Protected area', color: '#1c5cab' },
  government_land: { label: 'Government land', color: '#52514e' },
  water_body: { label: 'Water body', color: '#2a78d6' },
  watch_buffer: { label: 'Watch buffer', color: '#898781' },
  other: { label: 'Other boundary', color: '#52514e' },
}

export const fmtHa = (v: number) => (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2))
export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
export const fmtPct = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
export const humanize = (s: string) => s.replace(/_/g, ' ')
