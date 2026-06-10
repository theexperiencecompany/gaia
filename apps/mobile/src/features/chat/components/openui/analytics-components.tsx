/**
 * Analytics components — re-exported from the OpenUI config layer.
 *
 * The implementations live in:
 *   apps/mobile/src/config/openui/components/analytics.tsx
 *
 * All charts are rendered with react-native-svg (no Recharts dependency).
 * The SVG-based renderers measure available width via onLayout and draw
 * responsive axes, gridlines, and data shapes natively.
 */
export {
  AreaChartView,
  areaChartDef,
  areaChartSchema,
  BarChartView,
  barChartDef,
  barChartSchema,
  GaugeChartView,
  gaugeChartDef,
  gaugeChartSchema,
  LineChartView,
  lineChartDef,
  lineChartSchema,
  PieChartView,
  pieChartDef,
  pieChartSchema,
  RadarChartView,
  radarChartDef,
  radarChartSchema,
  ScatterChartView,
  StatRowView,
  scatterChartDef,
  scatterChartSchema,
  statRowDef,
  statRowSchema,
} from "@/config/openui/components/analytics";
