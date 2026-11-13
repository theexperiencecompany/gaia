import type { CodeChartData } from "../../../chat/types";
import type { Card, CardBlock } from "../types";
import { httpsUrl, sentenceCase } from "./card-parts";
import { countLabel } from "./count-label";

const CHART_TITLE = "Chart";

type ChartSpec = NonNullable<CodeChartData["chart_data"]>;

/**
 * One `chart_data` entry. No API tool emits the key today; the shared fixture
 * and the web's chart display give its two shapes: a bare chart spec, or a
 * rendered chart (as `code_data.charts` carries) with its image URL and spec.
 */
export type ChartDataItem = Partial<ChartSpec> &
  Partial<Pick<CodeChartData, "url" | "title" | "description" | "chart_data">>;

function chartTitle(chart: ChartDataItem): string {
  return chart.title ?? chart.chart_data?.title ?? CHART_TITLE;
}

/** "Bar chart of Commits by Day, 5 points": what the chart plots, for a platform that can't draw it. */
function specSummary(spec: Partial<ChartSpec>): string | undefined {
  const points = spec.elements?.length ?? 0;
  if (points === 0) return undefined;
  const kind = spec.type ? sentenceCase(`${spec.type} chart`) : CHART_TITLE;
  const axes =
    spec.x_label && spec.y_label
      ? ` of ${spec.y_label} by ${spec.x_label}`
      : "";
  return `${kind}${axes}, ${countLabel(points, "point")}`;
}

/** The chart image when it is hosted at https, else a one-line summary of its data. */
export function chartBlocks(chart: ChartDataItem): CardBlock[] {
  const url = httpsUrl(chart.url);
  if (url) return [{ kind: "image", url, alt: chartTitle(chart) }];
  const summary = specSummary(chart.chart_data ?? chart);
  return summary ? [{ kind: "text", markdown: summary }] : [];
}

/** One card per chart: the image when there is one, otherwise what it plots. */
export function buildChartCards(charts: ChartDataItem[]): Card[] {
  return charts.flatMap((chart): Card[] => {
    const blocks = chartBlocks(chart);
    if (blocks.length === 0) return [];
    if (chart.description) {
      blocks.push({ kind: "text", markdown: chart.description });
    }
    return [{ title: chartTitle(chart), accent: "brand", blocks, actions: [] }];
  });
}
