import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource, ImageSource, LngLatBoundsLike } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { BAND, TRANSITIONS } from '../theme'
import type { CaseFC, Transition } from '../types'

export interface ImageOverlay {
  url: string
  corners: [number, number][]
  opacity?: number
}

interface Props {
  districts?: GeoJSON.FeatureCollection | null
  boundaries?: GeoJSON.FeatureCollection | null
  cases?: CaseFC | null
  imagery?: ImageOverlay | null
  changeMask?: ImageOverlay | null
  aoiBoxes?: GeoJSON.FeatureCollection | null
  visibleTransitions?: Set<Transition>
  selectedCaseId?: string | null
  fitTo?: [number, number, number, number] | null
  onCaseClick?: (caseId: string) => void
  onAoiClick?: (aoiId: string) => void
  showDistricts?: boolean
  showBoundaries?: boolean
  heatmap?: boolean
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
const BLANK_PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='
type Quad = [[number, number], [number, number], [number, number], [number, number]]
const NOWHERE: Quad = [
  [0, 0.001],
  [0.001, 0.001],
  [0.001, 0],
  [0, 0],
]

const transitionColor = [
  'match',
  ['get', 'transition'],
  ...TRANSITIONS.flatMap((t) => [t.id, t.color]),
  '#898781',
] as unknown as maplibregl.ExpressionSpecification
const bandColor: maplibregl.ExpressionSpecification = [
  'match',
  ['get', 'priority_band'],
  'P1',
  BAND.P1.color,
  'P2',
  BAND.P2.color,
  'P3',
  BAND.P3.color,
  '#898781',
]

function centroids(fc: CaseFC): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: fc.features.map((f) => ({
      type: 'Feature',
      id: f.id,
      geometry: { type: 'Point', coordinates: f.properties.centroid },
      properties: f.properties,
    })),
  }
}

export default function MapView(p: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const handlers = useRef({ onCaseClick: p.onCaseClick, onAoiClick: p.onAoiClick })
  handlers.current = { onCaseClick: p.onCaseClick, onAoiClick: p.onAoiClick }
  const initialFit = useRef(p.fitTo)

  useEffect(() => {
    if (!el.current) return
    const m = new maplibregl.Map({
      container: el.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            maxzoom: 19,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [
          { id: 'bg', type: 'background', paint: { 'background-color': '#e8e7e2' } },
          { id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-saturation': -0.75, 'raster-opacity': 0.9 } },
        ],
      },
      ...(initialFit.current
        ? { bounds: initialFit.current as LngLatBoundsLike, fitBoundsOptions: { padding: 40 } }
        : { center: [92.6, 26.3] as [number, number], zoom: 6.4 }),
      attributionControl: { compact: true, customAttribution: 'Imagery: Copernicus Sentinel-2 (ESA)' },
    })
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')
    m.on('load', () => {
      m.addSource('imagery', { type: 'image', url: BLANK_PNG, coordinates: NOWHERE })
      m.addLayer({ id: 'imagery', type: 'raster', source: 'imagery', paint: { 'raster-fade-duration': 0 } })
      m.addSource('mask', { type: 'image', url: BLANK_PNG, coordinates: NOWHERE })
      m.addLayer({ id: 'mask', type: 'raster', source: 'mask', paint: { 'raster-opacity': 0.75, 'raster-fade-duration': 0 } })
      m.addSource('districts', { type: 'geojson', data: EMPTY })
      m.addLayer({ id: 'districts', type: 'line', source: 'districts', paint: { 'line-color': '#52514e', 'line-width': 0.8, 'line-dasharray': [3, 2], 'line-opacity': 0.7 } })
      m.addSource('aoiboxes', { type: 'geojson', data: EMPTY })
      m.addLayer({ id: 'aoiboxes-fill', type: 'fill', source: 'aoiboxes', paint: { 'fill-color': '#1c5cab', 'fill-opacity': 0.06 } })
      m.addLayer({ id: 'aoiboxes', type: 'line', source: 'aoiboxes', paint: { 'line-color': '#1c5cab', 'line-width': 1.5 } })
      m.addSource('boundaries', { type: 'geojson', data: EMPTY })
      m.addLayer({
        id: 'boundaries-fill',
        type: 'fill',
        source: 'boundaries',
        filter: ['!=', ['get', 'kind'], 'watch_buffer'],
        paint: { 'fill-color': '#2a78d6', 'fill-opacity': 0.07 },
      })
      m.addLayer({
        id: 'boundaries-buffer',
        type: 'line',
        source: 'boundaries',
        filter: ['==', ['get', 'kind'], 'watch_buffer'],
        paint: { 'line-color': '#52514e', 'line-width': 1, 'line-dasharray': [2, 2] },
      })
      m.addLayer({
        id: 'boundaries',
        type: 'line',
        source: 'boundaries',
        filter: ['!=', ['get', 'kind'], 'watch_buffer'],
        paint: {
          'line-color': ['match', ['get', 'kind'], 'government_land', '#0b0b0b', 'protected_area', '#1c5cab', '#2a78d6'],
          'line-width': 2,
        },
      })
      // Findings are keyed by finding_id (unique per run) so feature-state selection works.
      m.addSource('cases', { type: 'geojson', data: EMPTY, promoteId: 'finding_id' })
      m.addSource('case-pts', { type: 'geojson', data: EMPTY })
      m.addLayer({
        id: 'case-heat',
        type: 'heatmap',
        source: 'case-pts',
        layout: { visibility: 'none' },
        paint: {
          'heatmap-weight': ['/', ['get', 'priority_score'], 100],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 8, 12, 14, 40],
          'heatmap-opacity': 0.75,
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)', 0.2, '#fde7c8', 0.5, '#ec835a', 0.8, '#d03b3b', 1, '#8a1f1f',
          ],
        },
      })
      m.addLayer({
        id: 'cases-fill',
        type: 'fill',
        source: 'cases',
        paint: { 'fill-color': transitionColor, 'fill-opacity': 0.45 },
      })
      m.addLayer({
        id: 'cases-line',
        type: 'line',
        source: 'cases',
        paint: {
          'line-color': ['case', ['boolean', ['feature-state', 'sel'], false], '#ffd600', transitionColor],
          'line-width': ['case', ['boolean', ['feature-state', 'sel'], false], 3, 1.4],
        },
      })
      m.addLayer({
        id: 'case-pts',
        type: 'circle',
        source: 'case-pts',
        maxzoom: 13.5,
        // Markers only for queued cases; recorded-only findings stay as polygons.
        filter: ['!=', ['get', 'status'], 'RECORDED'],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 4, 12, 7],
          'circle-color': bandColor,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.5,
        },
      })
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 })
      for (const layer of ['cases-fill', 'case-pts']) {
        m.on('mousemove', layer, (e) => {
          const f = e.features?.[0]
          if (!f) return
          m.getCanvas().style.cursor = 'pointer'
          const pr = f.properties as Record<string, string | number>
          popup
            .setLngLat(e.lngLat)
            .setHTML(
              (pr.status === 'RECORDED'
                ? `<b>${pr.finding_id}</b> · ${pr.priority_band ?? ''} · recorded, not queued<br><span style="color:#52514e">${String(pr.triage ?? '').replace(/_/g, ' ')}</span><br>`
                : `<b>${pr.case_id}</b> · ${pr.priority_band} · ${String(pr.status).replace('_', ' ').toLowerCase()}<br>`) +
                `${pr.transition_label}<br>${Number(pr.area_ha).toFixed(2)} ha · conf. ${Number(pr.confidence).toFixed(2)}<br>` +
                `<span style="color:#52514e">${pr.observed_t1} → ${pr.observed_t2}</span>`,
            )
            .addTo(m)
        })
        m.on('mouseleave', layer, () => {
          m.getCanvas().style.cursor = ''
          popup.remove()
        })
        m.on('click', layer, (e) => {
          const id = e.features?.[0]?.properties?.case_id
          if (id) handlers.current.onCaseClick?.(String(id))
        })
      }
      m.on('click', 'aoiboxes-fill', (e) => {
        if (m.queryRenderedFeatures(e.point, { layers: ['cases-fill', 'case-pts'] }).length) return
        const id = e.features?.[0]?.properties?.id
        if (id) handlers.current.onAoiClick?.(String(id))
      })
      setReady(true)
    })
    map.current = m
    return () => {
      m.remove()
      map.current = null
    }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    ;(m.getSource('districts') as GeoJSONSource).setData(p.districts ?? EMPTY)
    m.setLayoutProperty('districts', 'visibility', p.showDistricts === false ? 'none' : 'visible')
  }, [ready, p.districts, p.showDistricts])

  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    ;(m.getSource('boundaries') as GeoJSONSource).setData(p.boundaries ?? EMPTY)
    const vis = p.showBoundaries === false ? 'none' : 'visible'
    for (const id of ['boundaries', 'boundaries-fill', 'boundaries-buffer']) m.setLayoutProperty(id, 'visibility', vis)
  }, [ready, p.boundaries, p.showBoundaries])

  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    ;(m.getSource('aoiboxes') as GeoJSONSource).setData(p.aoiBoxes ?? EMPTY)
  }, [ready, p.aoiBoxes])

  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    const fc = p.cases ?? (EMPTY as CaseFC)
    const vis = p.visibleTransitions
    const filtered: CaseFC = vis ? { ...fc, features: fc.features.filter((f) => vis.has(f.properties.transition)) } : fc
    ;(m.getSource('cases') as GeoJSONSource).setData(filtered)
    ;(m.getSource('case-pts') as GeoJSONSource).setData(centroids(filtered))
  }, [ready, p.cases, p.visibleTransitions])

  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    m.setLayoutProperty('case-heat', 'visibility', p.heatmap ? 'visible' : 'none')
    m.setLayoutProperty('case-pts', 'visibility', p.heatmap ? 'none' : 'visible')
  }, [ready, p.heatmap])

  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    m.removeFeatureState({ source: 'cases' })
    if (!p.selectedCaseId) return
    for (const f of p.cases?.features ?? []) {
      if (f.properties.case_id === p.selectedCaseId || f.properties.finding_id === p.selectedCaseId)
        m.setFeatureState({ source: 'cases', id: f.properties.finding_id }, { sel: true })
    }
  }, [ready, p.selectedCaseId, p.cases])

  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    const src = m.getSource('imagery') as ImageSource
    if (p.imagery) {
      src.updateImage({ url: p.imagery.url, coordinates: p.imagery.corners as never })
      m.setPaintProperty('imagery', 'raster-opacity', p.imagery.opacity ?? 1)
    } else {
      src.updateImage({ url: BLANK_PNG, coordinates: NOWHERE as never })
    }
  }, [ready, p.imagery])

  useEffect(() => {
    const m = map.current
    if (!ready || !m) return
    const src = m.getSource('mask') as ImageSource
    if (p.changeMask) src.updateImage({ url: p.changeMask.url, coordinates: p.changeMask.corners as never })
    else src.updateImage({ url: BLANK_PNG, coordinates: NOWHERE as never })
  }, [ready, p.changeMask])

  const fitKey = p.fitTo?.join(',')
  useEffect(() => {
    const m = map.current
    if (!ready || !m || !p.fitTo) return
    const [a, b, c, d] = p.fitTo
    m.fitBounds([[a, b], [c, d]] as LngLatBoundsLike, { padding: 40, duration: 700 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, fitKey])

  return (
    <div className="mapwrap">
      <div ref={el} style={{ position: 'absolute', inset: 0 }} />
    </div>
  )
}
