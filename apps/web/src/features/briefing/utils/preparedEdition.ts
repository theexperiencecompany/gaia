/** Folded in thirds; only an edition taller than this (height over width) gets a fourth panel. */
const FOUR_PANEL_ASPECT = 2.2;
const EDITION_MAX_WIDTH = 540;
/** Below this width the edition stops shrinking to fit the screen and scrolls instead. */
const EDITION_MIN_WIDTH = 360;
const VIEWPORT_GUTTER_PX = 24;
/** Room kept above and below the letter when it is fitted to the viewport. */
const VIEWPORT_MARGIN_PX = 64;
const MAX_PIXEL_RATIO = 2;

/** An edition decoded and cut into its fold panels at the size it will be shown. */
export interface PreparedEdition {
  /** Natural height over width. */
  aspect: number;
  /** Display width in CSS px, fitted to the viewport it was prepared for. */
  width: number;
  /** One bitmap per panel, top to bottom, already at display resolution. */
  panels: ImageBitmap[];
}

const prepared = new Map<string, Promise<PreparedEdition>>();

/** Fit the edition to the viewport height, but never below a readable width; past that it scrolls. */
function fittedWidth(aspect: number): number {
  const available = window.innerWidth - VIEWPORT_GUTTER_PX;
  const max = Math.min(EDITION_MAX_WIDTH, available);
  const min = Math.min(EDITION_MIN_WIDTH, available);
  const toFitHeight = (window.innerHeight - VIEWPORT_MARGIN_PX) / aspect;
  return Math.round(Math.min(max, Math.max(min, toFitHeight)));
}

async function decodeAndSlice(src: string): Promise<PreparedEdition> {
  const image = new window.Image();
  image.src = src;
  await image.decode();
  const aspect = image.naturalHeight / image.naturalWidth;
  const count = aspect > FOUR_PANEL_ASPECT ? 4 : 3;
  const width = fittedWidth(aspect);
  const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
  const panelWidth = Math.round(width * ratio);
  const panelHeight = Math.round((panelWidth * aspect) / count);
  const sourceHeight = image.naturalHeight / count;
  const panels = await Promise.all(
    Array.from({ length: count }, (_, index) =>
      createImageBitmap(
        image,
        0,
        index * sourceHeight,
        image.naturalWidth,
        sourceHeight,
        {
          resizeWidth: panelWidth,
          resizeHeight: panelHeight,
          resizeQuality: "high",
        },
      ),
    ),
  );
  return { aspect, width, panels };
}

/**
 * Decode the edition and cut its panels once per viewport size, so opening only
 * composites small bitmaps. A failed preparation is forgotten and retried next time.
 */
export function prepareEdition(src: string): Promise<PreparedEdition> {
  const key = `${src}@${window.innerWidth}x${window.innerHeight}`;
  const cached = prepared.get(key);
  if (cached) return cached;
  const pending = decodeAndSlice(src);
  prepared.set(key, pending);
  pending.catch(() => prepared.delete(key));
  return pending;
}
