export const THEME_COLOR = "#00bbff";

/** Maximum number of log lines retained per stream to limit memory usage */
export const LOG_BUFFER_LINES = 30;

export const BORDER = {
  primary: { style: "round" as const, color: THEME_COLOR },
  warning: { style: "round" as const, color: "yellow" },
  error: { style: "single" as const, color: "red" },
} as const;
