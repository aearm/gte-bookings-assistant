// The rest of ECharts that charts described in words may ask for (custom_echarts.SERIES_TYPES and
// COMPONENTS). Loaded only when such a chart is drawn.
import { use as registerParts } from 'echarts/core'
import {
  BoxplotChart, CandlestickChart, EffectScatterChart, FunnelChart, GaugeChart, GraphChart, LinesChart, ParallelChart,
  PictorialBarChart, RadarChart, SankeyChart, SunburstChart, ThemeRiverChart, TreeChart,
} from 'echarts/charts'
import {
  AriaComponent, BrushComponent, CalendarComponent, DataZoomComponent, GeoComponent, MarkAreaComponent,
  MarkLineComponent, MarkPointComponent, ParallelComponent, PolarComponent, RadarComponent, SingleAxisComponent,
  ToolboxComponent, VisualMapPiecewiseComponent,
} from 'echarts/components'

registerParts([
  BoxplotChart, CandlestickChart, EffectScatterChart, FunnelChart, GaugeChart, GraphChart, LinesChart, ParallelChart,
  PictorialBarChart, RadarChart, SankeyChart, SunburstChart, ThemeRiverChart, TreeChart,
  AriaComponent, BrushComponent, CalendarComponent, DataZoomComponent, GeoComponent, MarkAreaComponent,
  MarkLineComponent, MarkPointComponent, ParallelComponent, PolarComponent, RadarComponent, SingleAxisComponent,
  ToolboxComponent, VisualMapPiecewiseComponent,
])

export const ready = true
