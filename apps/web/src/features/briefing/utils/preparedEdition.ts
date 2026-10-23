import { findPaper } from "./paperBounds";

/** Folded in thirds; only an edition taller than this (height over width) gets a fourth panel. */
const FOUR_PANEL_ASPECT = 2.2;
const EDITION_MAX_WIDTH = 540;
/** Below this width the edition stops shrinking to fit the screen and scrolls instead. */
const EDITION_MIN_WIDTH = 360;
const VIEWPORT_GUTTER_PX = 24;
/** Room kept above and below the letter when it is fitted to the viewport. */
const VIEWPORT_MARGIN_PX = 64;
const MAX_PIXEL_RATIO = 2;
/** The folded letter in chat is drawn from the same panels, so they are cut wide enough for it too. */
export const LETTER_MAX_WIDTH = 460;
/** The chat letter lies tipped back this far; the open letter straightens from it. */
export const LETTER_TILT_DEG = 12;
export const LETTER_PERSPECTIVE_PX = 1100;
/** Paper darker than this takes light crease highlights instead of dark shading. */
const DARK_PAPER_LIGHTNESS = 0.45;

/** An edition decoded and cut into its fold panels at the size it will be shown. */
export interface PreparedEdition {
  /** Natural height over width. */
  aspect: number;
  /** Display width in CSS px, fitted to the viewport it was prepared for. */
  width: number;
  /** One bitmap per panel, top to bottom, already at display resolution. */
  panels: ImageBitmap[];
  /** The edition's paper colour as CSS rgb(), for the backs and edges of the folded sheet. */
  paper: string;
  isDarkPaper: boolean;
}

const prepared = new Map<string, Promise<PreparedEdition>>();

/** The back of the edition's paper: its own colour, shaded toward the crease it hangs from. */
export function paperBackGradient(paper: string): string {
  return `linear-gradient(180deg, color-mix(in srgb, ${paper} 80%, black) 0%, color-mix(in srgb, ${paper} 92%, black) 45%, ${paper} 100%)`;
}

/** Fit the edition to the viewport height, but never below a readable width; past that it scrolls. */
function fittedWidth(aspect: number): number {
  const available = window.innerWidth - VIEWPORT_GUTTER_PX;
  const max = Math.min(EDITION_MAX_WIDTH, available);
  const min = Math.min(EDITION_MIN_WIDTH, available);
  const toFitHeight = (window.innerHeight - VIEWPORT_MARGIN_PX) / aspect;
  return Math.round(Math.min(max, Math.max(min, toFitHeight)));
}

/** Perceived lightness of an sRGB colour, 0 (black) to 1 (white). */
function lightness([red, green, blue]: [number, number, number]): number {
  return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
}

async function decodeAndSlice(src: string): Promise<PreparedEdition> {
  const image = new window.Image();
  // The edition CDN allows any origin, so the paper can be read back from the pixels.
  image.crossOrigin = "anonymous";
  image.src = src;
  await image.decode();
  const sheet = findPaper(image);
  const aspect = sheet.height / sheet.width;
  const count = aspect > FOUR_PANEL_ASPECT ? 4 : 3;
  const width = fittedWidth(aspect);
  const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
  const panelWidth = Math.round(Math.max(width, LETTER_MAX_WIDTH) * ratio);
  const panelHeight = Math.round((panelWidth * aspect) / count);
  const sourceHeight = sheet.height / count;
  const panels = await Promise.all(
    Array.from({ length: count }, (_, index) =>
      createImageBitmap(
        image,
        sheet.x,
        sheet.y + index * sourceHeight,
        sheet.width,
        sourceHeight,
        {
          resizeWidth: panelWidth,
          resizeHeight: panelHeight,
          resizeQuality: "high",
        },
      ),
    ),
  );
  return {
    aspect,
    width,
    panels,
    paper: `rgb(${sheet.rgb.join(", ")})`,
    isDarkPaper: lightness(sheet.rgb) < DARK_PAPER_LIGHTNESS,
  };
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
