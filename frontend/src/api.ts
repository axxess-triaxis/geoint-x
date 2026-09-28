import type {
  Aoi,
  AoiDetail,
  Analytics,
  AssistantReply,
  BoundaryStat,
  CaseDetail,
  CaseFC,
  CaseRow,
  Candidate,
  Decision,
  Interpretation,
  Meta,
  Role,
  Run,
  CaseEvent,
} from './types'

// Demo identity (NOT authentication): the role switcher sets these headers.
let identity: { user: string; role: Role } = { user: 'a.sharma', role: 'analyst' }
export const setIdentity = (user: string, role: Role) => {
  identity = { user, role }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-Demo-User', identity.user)
  headers.set('X-Demo-Role', identity.role)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(path, { ...init, headers })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  meta: () => req<Meta>('/api/meta'),
  districts: () => req<GeoJSON.FeatureCollection>('/api/districts'),
  aois: () => req<Aoi[]>('/api/aois'),
  aoi: (id: string) => req<AoiDetail>(`/api/aois/${id}`),
  corners: (id: string) => req<[number, number][]>(`/api/aois/${id}/corners`),
  sceneUrl: (aoi: string, scene: string) => `/api/aois/${aoi}/scenes/${scene}/truecolor.png`,
  importPolygon: (aoi: string, body: { name: string; kind: string; geometry: unknown; source: string; official: boolean }) =>
    post<unknown>(`/api/aois/${aoi}/polygons`, body),
  runDetection: (aoi_id: string, t1_scene_id: string, t2_scene_id: string) =>
    post<{ run: Run; finding_count: number; case_ids: string[] }>('/api/runs', { aoi_id, t1_scene_id, t2_scene_id }),
  run: (id: string) => req<Run & { findings: GeoJSON.FeatureCollection }>(`/api/runs/${id}`),
  cases: (q: Record<string, string> = {}) => req<CaseFC>(`/api/cases?${new URLSearchParams(q)}`),
  caseDetail: (id: string) => req<CaseDetail>(`/api/cases/${id}`),
  action: (id: string, body: { action: string; note?: string; reject_reason?: string; assignee?: string }) =>
    post<CaseRow>(`/api/cases/${id}/actions`, body),
  attach: (id: string, file: File, note: string, kind: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('note', note)
    fd.append('kind', kind)
    return req<CaseRow>(`/api/cases/${id}/attachments`, { method: 'POST', body: fd })
  },
  interpret: (id: string) =>
    post<{ interpretation: Interpretation; meta: Record<string, unknown> }>(`/api/cases/${id}/interpret`),
  analytics: () => req<Analytics>('/api/analytics'),
  boundaries: () => req<{ monitored_boundaries: BoundaryStat[]; note: string }>('/api/boundaries'),
  ask: (question: string) => post<AssistantReply>('/api/assistant', { question }),
  plan: () => req<{ now: string; candidates: Candidate[] }>('/api/scheduler/plan'),
  cycle: (strategy: string) =>
    post<{ decision: Decision; run: Run | null; case_ids: string[] }>('/api/scheduler/cycle', { strategy }),
  decisions: () => req<Decision[]>('/api/scheduler/decisions'),
  activity: () => req<CaseEvent[]>('/api/activity'),
}
