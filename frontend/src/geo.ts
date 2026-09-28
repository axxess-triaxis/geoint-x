import type { Aoi } from './types'

export function aoiBoxes(aois: Aoi[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: aois.map((a) => {
      const [x0, y0, x1, y1] = a.bbox
      return {
        type: 'Feature',
        properties: { id: a.id, name: a.name },
        geometry: { type: 'Polygon', coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]] },
      }
    }),
  }
}

export function unionBbox(aois: Aoi[]): [number, number, number, number] {
  return [
    Math.min(...aois.map((a) => a.bbox[0])),
    Math.min(...aois.map((a) => a.bbox[1])),
    Math.max(...aois.map((a) => a.bbox[2])),
    Math.max(...aois.map((a) => a.bbox[3])),
  ]
}
