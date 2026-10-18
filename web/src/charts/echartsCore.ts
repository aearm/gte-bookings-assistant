// ECharts with only what the app's charts use (chart_options.py): bars, lines, areas, donuts,
// scatter, heatmaps, treemaps and the world map; drawn on canvas. Charts described in words may use
// more (funnel, sunburst, radar, ...): those parts come from echartsExtra.ts, loaded when needed.
import { use as registerParts } from 'echarts/core'
import { BarChart, HeatmapChart, LineChart, MapChart, PieChart, ScatterChart, TreemapChart } from 'echarts/charts'
import {
  AxisPointerComponent, DatasetComponent, GridComponent, LegendComponent, LegendScrollComponent, TitleComponent,
  TooltipComponent, TransformComponent, VisualMapContinuousComponent,
} from 'echarts/components'
import { LabelLayout, LegacyGridContainLabel } from 'echarts/features'
import { CanvasRenderer } from 'echarts/renderers'

registerParts([
  BarChart, LineChart, PieChart, ScatterChart, HeatmapChart, TreemapChart, MapChart,
  TitleComponent, TooltipComponent, LegendComponent, LegendScrollComponent, GridComponent, AxisPointerComponent,
  DatasetComponent, TransformComponent, VisualMapContinuousComponent,
  LabelLayout, LegacyGridContainLabel, // the options use grid.containLabel (ECharts 5 behaviour)
  CanvasRenderer,
])

export { init, registerMap, getMap } from 'echarts/core'
export type { ECharts } from 'echarts/core'
