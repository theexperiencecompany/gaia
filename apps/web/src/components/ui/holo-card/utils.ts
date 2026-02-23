import { POSITION_CALC } from "./constants";

interface BackgroundPosition {
  lp: number;
  tp: number;
}

/**
 * Calculates the background position based on cursor/touch position
 * @param offsetX - X offset from the element
 * @param offsetY - Y offset from the element
 * @param width - Element width
 * @param height - Element height
 * @returns Background position object with lp (left percent) and tp (top percent)
 */
export function calculateBackgroundPosition(
  offsetX: number,
  offsetY: number,
  width: number,
  height: number,
): BackgroundPosition {
  const px = Math.abs(Math.floor((100 / width) * offsetX) - 100);
  const py = Math.abs(Math.floor((100 / height) * offsetY) - 100);

  const lp = 50 + (px - 50) / POSITION_CALC.DAMPING_FACTOR;
  const tp = 50 + (py - 50) / POSITION_CALC.DAMPING_FACTOR;

  return { lp, tp };
}
