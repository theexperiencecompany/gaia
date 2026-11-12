import {
  BAR_LABEL_CHAR_PX,
  BAR_LABEL_GAP_PX,
  BAR_VALUE_AXIS_PX,
} from "../constants";

/** Whether every category label fits under its own vertical bar in a figure this wide. */
export function labelsFitUnderBars(width: number, labels: string[]): boolean {
  const longest = Math.max(0, ...labels.map((label) => label.length));
  const slot = (width - BAR_VALUE_AXIS_PX) / Math.max(1, labels.length);
  return slot >= longest * BAR_LABEL_CHAR_PX + BAR_LABEL_GAP_PX;
}
