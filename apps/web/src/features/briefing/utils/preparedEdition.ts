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
/** The paper colour is read from the edition's left margin, a strip this share of its width. */
const PAPER_SAMPLE_SHARE = 0.02;

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

/** Average the edition's left margin down to one pixel: its paper. */
function paperColour(image: HTMLImageElement): string {
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) {
    throw new Error("No 2D canvas to read the edition's paper colour from");
  }
  const strip = Math.max(
    1,
    Math.round(image.naturalWidth * PAPER_SAMPLE_SHARE),
  );
  context.drawImage(image, 0, 0, strip, image.naturalHeight, 0, 0, 1, 1);
  const [red, green, blue] = context.getImageData(0, 0, 1, 1).data;
  return `rgb(${red}, ${green}, ${blue})`;
}

async function decodeAndSlice(src: string): Promise<PreparedEdition> {
  const image = new window.Image();
  // The edition CDN allows any origin, so the paper colour can be read back.
  image.crossOrigin = "anonymous";
  image.src = src;
  await image.decode();
  const aspect = image.naturalHeight / image.naturalWidth;
  const count = aspect > FOUR_PANEL_ASPECT ? 4 : 3;
  const width = fittedWidth(aspect);
  const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
  const panelWidth = Math.round(Math.max(width, LETTER_MAX_WIDTH) * ratio);
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
  return { aspect, width, panels, paper: paperColour(image) };
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
