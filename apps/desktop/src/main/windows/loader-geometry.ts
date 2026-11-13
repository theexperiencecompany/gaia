/**
 * Loader Geometry Module
 *
 * Pure window-size math for the boot loader (splash + main window start
 * bounds). Dependency-free on purpose: anything importing Electron cannot be
 * unit-tested on machines without the Electron binary (e.g. Linux CI), so the
 * geometry lives here and the Electron calls stay in `windows/splash`.
 *
 * @module windows/loader-geometry
 */

/** Loader size as a fraction of the display work area — big enough that the
 * shell skeleton is legible, small enough to still read as a loader that
 * scales up into the full app. */
const LOADER_WORK_AREA_RATIO = 0.72;

/** Bounds for the loader so it stays usable on tiny and huge displays. */
const LOADER_MIN_WIDTH = 880;
const LOADER_MIN_HEIGHT = 600;
const LOADER_MAX_WIDTH = 1280;
const LOADER_MAX_HEIGHT = 820;

/** Work-area size (display minus menu bar / Dock). */
export interface WorkAreaSize {
  width: number;
  height: number;
}

/** A work area with its screen origin — what `screen.getPrimaryDisplay().workArea` yields. */
export interface WorkArea extends WorkAreaSize {
  x: number;
  y: number;
}

/** Normal (restored) main-window size — the frame a restore lands on. */
export const MAIN_NORMAL_WIDTH = 1400;
export const MAIN_NORMAL_HEIGHT = 900;

/**
 * Resolve the loader window size for a given work area, in CSS pixels.
 *
 * 72% of the work area, clamped to the usable bounds and never larger than the
 * work area itself, so it fits everything from an 800×600 panel to a 4K display.
 * Kept free of Electron imports so it stays unit-testable.
 */
export function resolveLoaderSize(workArea: WorkAreaSize): {
  width: number;
  height: number;
} {
  const width = Math.round(
    Math.min(
      Math.max(workArea.width * LOADER_WORK_AREA_RATIO, LOADER_MIN_WIDTH),
      LOADER_MAX_WIDTH,
      workArea.width,
    ),
  );
  const height = Math.round(
    Math.min(
      Math.max(workArea.height * LOADER_WORK_AREA_RATIO, LOADER_MIN_HEIGHT),
      LOADER_MAX_HEIGHT,
      workArea.height,
    ),
  );
  return { width, height };
}

/**
 * Resolve the normal main-window frame, centered in the work area.
 *
 * The boot scale-up maximises FROM the small loader bounds, so without this
 * the first restore would land on the loader size instead of the real normal
 * frame. Pure so it is unit-testable; the Electron wiring lives in
 * `windows/main`.
 */
export function resolveNormalBounds(workArea: WorkArea): {
  x: number;
  y: number;
  width: number;
  height: number;
} {
  const width = Math.min(MAIN_NORMAL_WIDTH, workArea.width);
  const height = Math.min(MAIN_NORMAL_HEIGHT, workArea.height);
  return {
    width,
    height,
    x: Math.round(workArea.x + Math.max(0, (workArea.width - width) / 2)),
    y: Math.round(workArea.y + Math.max(0, (workArea.height - height) / 2)),
  };
}
