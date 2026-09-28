export type CaseStatus = 'UNVERIFIED' | 'UNDER_REVIEW' | 'CONFIRMED' | 'REJECTED'
export type Band = 'P1' | 'P2' | 'P3'
export type Role = 'analyst' | 'reviewer' | 'supervisor'
export type Transition =
  | 'water_loss'
  | 'water_gain'
  | 'forest_clearing'
  | 'cropland_to_bare_or_built'
  | 'vegetation_to_bare_or_built'
  | 'wetland_vegetation_loss'
  | 'revegetation'

export interface Meta {
  data_mode: string
  pack_built_at: string | null
  pack_note: string | null
  sources: Record<string, string>
  ai: { enabled: boolean; provider: string | null; model: string | null; fallback: string }
  algorithm: string
  identity: string
}

export interface SceneRef {
  scene_id: string
  collection: string
  datetime: string
  cloud_cover: number | null
  aoi_valid_fraction: number | null
  platform: string | null
  source_href: string | null
}

export interface Aoi {
  id: string
  name: string
  mode: 'lulc' | 'encroachment'
  description: string
  bbox: [number, number, number, number]
  district: string | null
  monitoring_active: boolean
  last_observed_at: string | null
  last_run_id: string | null
  scene_count: number
  case_count: number
  open_cases: number
  p1_open: number
  changed_area_ha: number
}

export interface Run {
  id: string
  aoi_id: string
  t1_scene_id: string
  t2_scene_id: string
  t1_datetime: string
  t2_datetime: string
  later_scene_ids: string[]
  triggered_by: string
  algorithm_version: string
  stats: Record<string, number>
  artifacts: EvidenceItem[]
  overlay_corners: [number, number][]
  finding_count: number
  case_count: number
  created_at: string
}

export interface AoiDetail extends Omit<Aoi, 'scene_count' | 'case_count' | 'open_cases' | 'p1_open' | 'changed_area_ha'> {
  polygons: GeoJSON.FeatureCollection
  scenes: SceneRef[]
  catalog_stats: { acquisitions: number; clear_le_20pct: number; first: string | null; last: string | null }
  runs: Run[]
}

export interface EvidenceItem {
  id: string
  kind: string
  description: string
  uri: string | null
  sha256: string | null
}

export interface Factor {
  name: string
  value: number
  weight: number
  contribution?: number
  explanation: string
}

export interface Overlap {
  polygon_id: string
  polygon_name: string
  polygon_kind: string
  overlap_ha: number
  fraction_of_finding_inside: number
  crosses_boundary: boolean
  within_buffer: boolean
  distance_to_boundary_m: number
}

export interface Finding {
  id: string
  run_id: string
  aoi_id: string
  transition: Transition
  transition_label: string
  geometry: GeoJSON.Geometry
  centroid: [number, number]
  area_ha: number
  pixel_count: number
  t1: SceneRef
  t2: SceneRef
  index_means_t1: Record<string, number>
  index_means_t2: Record<string, number>
  index_deltas: Record<string, number>
  baseline_landcover: Record<string, number>
  persistence: number | null
  confidence: number
  confidence_factors: Factor[]
  overlaps: Overlap[]
  district: string | null
  algorithm_version: string
  evidence: EvidenceItem[]
  caveats: string[]
}

export interface Interpretation {
  summary: string
  evidence_refs: string[]
  plausible_explanations: string[]
  verification_steps: string[]
  caveats: string[]
  source: 'gemini' | 'template'
  model: string | null
  meta?: Record<string, unknown>
  generated_at?: string
}

export interface CaseRow {
  id: string
  finding_id: string
  run_id: string
  aoi_id: string
  status: CaseStatus
  priority_score: number
  priority_band: Band
  priority: { score: number; band: Band; factors: Factor[]; engine_version: string }
  transition: Transition
  area_ha: number
  confidence: number
  district: string | null
  observed_t1: string
  observed_t2: string
  assignee: string | null
  reject_reason: string | null
  interpretation: Interpretation | null
  created_at: string
  updated_at: string
  decided_at: string | null
}

export interface CaseEvent {
  id: number
  case_id: string
  seq: number
  ts: string
  actor: string
  role: string
  action: string
  from_status: string | null
  to_status: string | null
  payload: Record<string, unknown>
  prev_hash: string
  hash: string
}

export interface CaseDetail {
  case: CaseRow
  finding: Finding
  run: Run | null
  events: CaseEvent[]
  audit_chain: { ok: boolean; checked: number; reason: string | null }
  allowed_actions: string[]
  reject_reasons: string[]
}

export interface CaseProps {
  case_id: string
  finding_id: string
  aoi_id?: string
  /** Case status, or RECORDED / CASE for run findings. */
  status: CaseStatus | 'RECORDED' | 'CASE'
  linked_case_id?: string | null
  triage?: string | null
  priority_band: Band
  priority_score: number
  transition: Transition
  transition_label: string
  area_ha: number
  confidence: number
  district: string | null
  observed_t1: string
  observed_t2: string
  centroid: [number, number]
}

export type CaseFC = GeoJSON.FeatureCollection<GeoJSON.Geometry, CaseProps>

export interface Candidate {
  key: string
  aoi_id: string
  aoi_name: string
  district: string | null
  prev_scene_id: string
  prev_date: string
  next_scene_id: string
  next_date: string
  terms: Record<string, number>
  weights: Record<string, number>
  p_usable: number
  cost: number
  value: number
  score: number
  notes: string[]
}

export interface Decision {
  id: number
  ts: string
  strategy: string
  decision_source: string
  chosen_aoi_id: string | null
  chosen_scene_id: string | null
  reason: string
  candidates: Candidate[]
  executed_run_id: string | null
}

export interface Composition {
  scene_id: string
  date: string
  clear_fraction: number
  shares: Record<string, number>
  area_ha: Record<string, number>
}

export interface Analytics {
  totals: {
    monitored_areas: number
    analyses: number
    cases: number
    open: number
    p1_open: number
    confirmed: number
    rejected: number
    rejection_rate: number | null
    changed_area_ha: number
    case_area_ha: number
    regions: number
  }
  triage: Record<string, number>
  status_counts: Record<string, number>
  by_district: Record<string, { regions: number; area_ha: number }>
  by_transition: Record<string, { regions: number; area_ha: number; cases: number; confirmed: number; rejected: number }>
  by_period: Record<string, Record<string, number>>
  reject_reasons: Record<string, number>
  coverage: {
    aoi_id: string
    name: string
    mode: string
    district: string | null
    area_km2: number
    analyses: number
    last_observed: string | null
    days_since_observation: number | null
    catalog_acquisitions: number
    catalog_clear_share: number | null
    monitoring_active: boolean
  }[]
  land_composition: Record<string, Composition[]>
  notes: string[]
}

export interface BoundaryStat {
  polygon_id: string
  polygon: string
  kind: string
  aoi_id: string
  boundary_source: string
  official_boundary: boolean
  changed_area_inside_ha: number
  changed_area_in_buffer_ha: number
  case_ids: string[]
  open_case_ids: string[]
}

export interface AssistantReply {
  question: string
  answer: string
  answer_source: string
  route_source: string
  tool: string
  args: Record<string, unknown>
  result: Record<string, unknown>
  guard_problems: string[]
  focus_case_ids: string[]
}
