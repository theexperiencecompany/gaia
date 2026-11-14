/** The artifact categorical palette: colour-blind separated and 3:1 on white and black, so one set serves both modes. */
export const ARTIFACT_PALETTE = [
  "#0a9ad6",
  "#e06a2b",
  "#1d9e6c",
  "#8b7cf0",
  "#d5568f",
] as const;

/** Above this many rows a DataTable offers a filter box. */
export const TABLE_FILTER_MIN_ROWS = 10;

/** A vertical bar chart's axis label: about this wide per character at its 12px size. */
export const BAR_LABEL_CHAR_PX = 7;
/** Room each bar label keeps clear of its neighbours, and the value axis's share of the width. */
export const BAR_LABEL_GAP_PX = 8;
export const BAR_VALUE_AXIS_PX = 40;
