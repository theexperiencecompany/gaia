import { frontPaper, type Rgb } from "./frontPaper";
import {
  type EditionSource,
  findPaper,
  type PaperSheet,
  straighten,
} from "./paperBounds";

/** Folded in thirds; only an edition taller than this (height over width) gets a fourth panel. */
const FOUR_PANEL_ASPECT = 2.2;
const EDITION_MAX_WIDTH = 540;
/** Below this width the edition stops shrinking to fit the screen and scrolls instead. */
const EDITION_MIN_WIDTH = 360;
const VIEWPORT_GUTTER_PX = 24;
/** Room kept above and below the letter when it is fitted to the viewport. */
const VIEWPORT_MARGIN_PX = 64;
const MAX_PIXEL_RATIO = 2;
/** A marked fold is kept within this share of the sheet, so neither the front nor the rest collapses. */
const FRONT_SHARE_RANGE = [0.12, 0.6] as const;
/** A marked paper box is cut this share of its width inside, clear of a tilt's corners and its antialiased edge. */
const PAPER_BOX_INSET = 0.004;
/** The folded letter in chat is drawn from the same panels, so they are cut wide enough for it too. */
export const LETTER_MAX_WIDTH = 460;
/** The chat letter lies tipped back this far; the open letter straightens from it. */
export const LETTER_TILT_DEG = 12;
export const LETTER_PERSPECTIVE_PX = 1100;
/** Paper darker than this takes light crease highlights instead of dark shading. */
const DARK_PAPER_LIGHTNESS = 0.45;

/** Where the edition says its letter folds and where its paper lies, as shares of its image. */
export interface EditionLayout {
  fold: number | null;
  /** [left, top, right, bottom]; null when the paper fills the image. */
  paper: number[] | null;
}

/** An edition decoded and cut into its fold panels at the size it will be shown. */
export interface PreparedEdition {
  /** Natural height over width. */
  aspect: number;
  /** Display width in CSS px, fitted to the viewport it was prepared for. */
  width: number;
  /** One bitmap per panel, top to bottom, already at display resolution. */
  panels: ImageBitmap[];
  /** Each panel's share of the sheet's height, top to bottom; the front ends at the edition's fold. */
  shares: number[];
  /** The front panel's paper colour as CSS rgb(), for the backs and edges of the folded sheet. */
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
function lightness([red, green, blue]: Rgb): number {
  return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
}

/** The front ends where the edition marks its fold; the rest folds evenly. Unmarked editions fold evenly. */
function panelShares(count: number, foldInSheet: number | null): number[] {
  if (foldInSheet === null)
    return Array.from({ length: count }, () => 1 / count);
  const front = Math.min(
    FRONT_SHARE_RANGE[1],
    Math.max(FRONT_SHARE_RANGE[0], foldInSheet),
  );
  const rest = (1 - front) / (count - 1);
  return [front, ...Array.from({ length: count - 1 }, () => rest)];
}

/** The sheet as the edition's own paper marker places it, a hair inside its box. */
function markedSheet(image: HTMLImageElement, paper: number[]): PaperSheet {
  const [left, top, right, bottom] = paper;
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  const inset = (right - left) * width * PAPER_BOX_INSET;
  return {
    x: left * width + inset,
    y: top * height + inset,
    width: (right - left) * width - 2 * inset,
    height: (bottom - top) * height - 2 * inset,
    rgb: [0, 0, 0],
    desk: [0, 0, 0],
    tilt: 0,
  };
}

async function decodeAndSlice(
  src: string,
  { fold, paper }: EditionLayout,
): Promise<PreparedEdition> {
  const image = new window.Image();
  // The edition CDN allows any origin, so the paper can be read back from the pixels.
  image.crossOrigin = "anonymous";
  image.src = src;
  await image.decode();
  const drawn: EditionSource = {
    source: image,
    width: image.naturalWidth,
    height: image.naturalHeight,
  };
  // A marked paper box is exact; only an unmarked edition is read for its desk.
  const asDrawn = paper ? markedSheet(image, paper) : findPaper(drawn);
  // A sheet set at an angle on its desk is turned square first, so its border survives the crop.
  const edition = asDrawn.tilt ? straighten(image, asDrawn) : drawn;
  const sheet = asDrawn.tilt ? findPaper(edition) : asDrawn;
  const aspect = sheet.height / sheet.width;
  const count = aspect > FOUR_PANEL_ASPECT ? 4 : 3;
  // Turning a tilted sheet square lifts one end of the fold line; the cut moves up by
  // that much, so nothing below the marker rises into the front.
  const turnLift = (sheet.width / 2) * Math.abs(Math.sin(asDrawn.tilt));
  const foldInSheet =
    fold === null
      ? null
      : (fold * image.naturalHeight - turnLift - sheet.y) / sheet.height;
  const shares = panelShares(count, foldInSheet);
  const width = fittedWidth(aspect);
  const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
  const panelWidth = Math.round(Math.max(width, LETTER_MAX_WIDTH) * ratio);
  const starts = shares.map((_, index) =>
    shares.slice(0, index).reduce((sum, share) => sum + share, 0),
  );
  const panels = await Promise.all(
    shares.map((share, index) =>
      createImageBitmap(
        edition.source,
        sheet.x,
        sheet.y + starts[index] * sheet.height,
        sheet.width,
        share * sheet.height,
        {
          resizeWidth: panelWidth,
          resizeHeight: Math.max(1, Math.round(panelWidth * aspect * share)),
          resizeQuality: "high",
        },
      ),
    ),
  );
  const frontRgb = frontPaper(panels[0]);
  return {
    aspect,
    width,
    panels,
    shares,
    paper: `rgb(${frontRgb.join(", ")})`,
    isDarkPaper: lightness(frontRgb) < DARK_PAPER_LIGHTNESS,
  };
}

/**
 * Decode the edition and cut its panels once per viewport size, so opening only
 * composites small bitmaps. A failed preparation is forgotten and retried next time.
 */
export function prepareEdition(
  src: string,
  layout: EditionLayout,
): Promise<PreparedEdition> {
  const key = `${src}@${layout.fold ?? "even"}@${layout.paper?.join(",") ?? "drawn"}@${window.innerWidth}x${window.innerHeight}`;
  const cached = prepared.get(key);
  if (cached) return cached;
  const pending = decodeAndSlice(src, layout);
  prepared.set(key, pending);
  pending.catch(() => prepared.delete(key));
  return pending;
}
