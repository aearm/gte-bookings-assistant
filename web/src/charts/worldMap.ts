/* eslint-disable @typescript-eslint/no-explicit-any -- ECharts options are free-form JSON */
// The world map the map charts draw on: world-atlas' countries (TopoJSON, 1:110m) turned into GeoJSON
// whose features carry their ISO-3 code in properties.iso_a3, registered with ECharts as "world".
// The file (~110 KB) and topojson-client load only when a map chart is first drawn.
import { NAME_TO_ISO3, NUMERIC_TO_ISO3 } from './isoCodes'

type Feature = { type: 'Feature'; id?: string | number; properties: Record<string, any>; geometry: unknown }
export type WorldGeoJson = { type: 'FeatureCollection'; features: Feature[] }

const names: Record<string, string> = {} // ISO-3 -> the atlas' country name

/** The atlas' name of a country (for countries the result has no row for). */
export const countryName = (code: string): string | undefined => names[code]

/** GeoJSON features with properties.iso_a3, leaving out `exclude` (Antarctica, as the old charts crop it). */
export function toWorldGeoJson(collection: { features: Feature[] }, exclude: string[] = ['ATA']): WorldGeoJson {
  const skip = new Set(exclude)
  const features: Feature[] = []
  for (const f of collection.features) {
    const name = String(f.properties?.name ?? '')
    const code = NUMERIC_TO_ISO3[String(f.id ?? '').padStart(3, '0')] ?? NAME_TO_ISO3[name]
    if (!code || skip.has(code)) continue
    names[code] = name
    features.push({ ...f, properties: { ...f.properties, iso_a3: code } })
  }
  return { type: 'FeatureCollection', features }
}

let loading: Promise<void> | null = null

/** Registers the "world" map once (later calls wait for the first). */
export function ensureWorldMap(registerMap: (name: string, geoJson: any) => void, exclude?: string[]): Promise<void> {
  loading ??= (async () => {
    const [{ feature }, url] = await Promise.all([
      import('topojson-client'),
      import('world-atlas/countries-110m.json?url').then((m) => m.default),
    ])
    const topology = await (await fetch(url)).json()
    const countries = feature(topology, topology.objects.countries) as unknown as { features: Feature[] }
    registerMap('world', toWorldGeoJson(countries, exclude) as any)
  })().catch((error) => {
    loading = null // try again on the next chart
    throw error
  })
  return loading
}
