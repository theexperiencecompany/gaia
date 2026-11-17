import {
  BRIEF_LETTER_MAX_WIDTH_PX,
  CHAT_LETTER_MAX_WIDTH_PX,
  LETTER_VIEWPORT_GUTTER_PX,
} from "../letterTokens";
import { frontPaper, type Rgb } from "./frontPaper";
import {
  type EditionSource,
  findPaper,
  type PaperBox,
  straighten,
} from "./paperBounds";

/** Folded in thirds; only an edition taller than this (height over width) gets a fourth panel. */
const FOUR_PANEL_ASPECT = 2.2;
const MAX_PIXEL_RATIO = 2;
/** A marked fold is kept within this share of the sheet, so neither the front nor the rest collapses. */
const FRONT_SHARE_RANGE = [0.12, 0.6] as const;
/** A marked paper box is cut this share of its width inside, clear of a tilt's corners and its antialiased edge. */
const PAPER_BOX_INSET = 0.004;
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
  /** The whole sheet in one bitmap, shown once the letter lies open so no panel seam is left. */
  sheet: ImageBitmap;
  /** Each panel's share of the sheet's height, top to bottom; the front ends at the edition's fold. */
  shares: number[];
  /** The front panel's paper colour as CSS rgb(), for the backs and edges of the folded sheet. */
  paper: string;
  isDarkPaper: boolean;
}

/** Prepared editions nobody holds that are kept for a quick reopen; each holds ~25 MB of bitmaps. */
const IDLE_EDITIONS_KEPT = 3;

interface Preparation {
  edition: Promise<PreparedEdition>;
  holders: number;
}

/** Every preparation by key, least recently used first. */
const preparations = new Map<string, Preparation>();

/** An edition kept prepared until released; its bitmaps stay open while any hold remains. */
export interface EditionHold {
  edition: Promise<PreparedEdition>;
  release: () => void;
}

/** The edition at its full letter width, or the screen's when narrower; a tall one scrolls. */
function fittedWidth(): number {
  return Math.round(
    Math.min(
      BRIEF_LETTER_MAX_WIDTH_PX,
      window.innerWidth - LETTER_VIEWPORT_GUTTER_PX,
    ),
  );
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

/** The paper as the edition's own marker places it, a hair inside its box. */
function markedBox(image: HTMLImageElement, paper: number[]): PaperBox {
  const [left, top, right, bottom] = paper;
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  const inset = (right - left) * width * PAPER_BOX_INSET;
  return {
    x: left * width + inset,
    y: top * height + inset,
    width: (right - left) * width - 2 * inset,
    height: (bottom - top) * height - 2 * inset,
  };
}

/**
 * Where the paper lies, and the image to cut it from. A marked box is exact;
 * only an unmarked edition is read for its desk, and a sheet set at an angle on
 * it is turned square first, so its border survives the crop.
 * INTEGRATION(P-api2): once every edition carries the box Chromium measures, the
 * unmarked branch, straighten() and all of paperBounds.ts are deleted.
 */
function locatePaper(
  image: HTMLImageElement,
  drawn: EditionSource,
  paper: number[] | null,
): { edition: EditionSource; box: PaperBox; tilt: number } {
  if (paper) return { edition: drawn, box: markedBox(image, paper), tilt: 0 };
  const found = findPaper(drawn);
  if (!found.tilt) return { edition: drawn, box: found, tilt: 0 };
  const edition = straighten(image, found);
  return { edition, box: findPaper(edition), tilt: found.tilt };
}

async function decodeAndSlice(
  src: string,
  { fold, paper }: EditionLayout,
  width: number,
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
  const { edition, box: sheet, tilt } = locatePaper(image, drawn, paper);
  const aspect = sheet.height / sheet.width;
  const count = aspect > FOUR_PANEL_ASPECT ? 4 : 3;
  // Turning a tilted sheet square lifts one end of the fold line; the cut moves up by
  // that much, so nothing below the marker rises into the front.
  const turnLift = (sheet.width / 2) * Math.abs(Math.sin(tilt));
  const foldInSheet =
    fold === null
      ? null
      : (fold * image.naturalHeight - turnLift - sheet.y) / sheet.height;
  const shares = panelShares(count, foldInSheet);
  const ratio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
  const panelWidth = Math.round(
    Math.max(width, CHAT_LETTER_MAX_WIDTH_PX) * ratio,
  );
  const starts = shares.map((_, index) =>
    shares.slice(0, index).reduce((sum, share) => sum + share, 0),
  );
  const cut = (start: number, share: number) =>
    createImageBitmap(
      edition.source,
      sheet.x,
      sheet.y + start * sheet.height,
      sheet.width,
      share * sheet.height,
      {
        resizeWidth: panelWidth,
        resizeHeight: Math.max(1, Math.round(panelWidth * aspect * share)),
        resizeQuality: "high",
      },
    );
  const [whole, ...panels] = await Promise.all([
    cut(0, 1),
    ...shares.map((share, index) => cut(starts[index], share)),
  ]);
  const frontRgb = frontPaper(panels[0]);
  return {
    aspect,
    width,
    panels,
    sheet: whole,
    shares,
    paper: `rgb(${frontRgb.join(", ")})`,
    isDarkPaper: lightness(frontRgb) < DARK_PAPER_LIGHTNESS,
  };
}

function closeBitmaps(edition: PreparedEdition): void {
  edition.sheet.close();
  for (const panel of edition.panels) panel.close();
}

/** Drop the least recently used editions nobody holds, past the few kept, and free their bitmaps. */
function evictIdle(): void {
  const idle = [...preparations].filter(([, entry]) => entry.holders === 0);
  for (const [key, entry] of idle.slice(0, -IDLE_EDITIONS_KEPT)) {
    preparations.delete(key);
    // A failed preparation has nothing to free; its holders already saw the error.
    entry.edition.then(closeBitmaps, () => undefined);
  }
}

/**
 * Decode the edition and cut its panels once per display width, so opening only
 * composites small bitmaps. Every viewport wider than the letter shares one width.
 * A failed preparation is forgotten and retried next time.
 */
export function holdEdition(src: string, layout: EditionLayout): EditionHold {
  const width = fittedWidth();
  const key = `${src}@${layout.fold ?? "even"}@${layout.paper?.join(",") ?? "drawn"}@${width}`;
  let entry = preparations.get(key);
  if (entry) {
    preparations.delete(key);
  } else {
    const created: Preparation = {
      edition: decodeAndSlice(src, layout, width),
      holders: 0,
    };
    created.edition.catch(() => {
      if (preparations.get(key) === created) preparations.delete(key);
    });
    entry = created;
  }
  preparations.set(key, entry);
  entry.holders += 1;
  const held = entry;
  let isReleased = false;
  return {
    edition: held.edition,
    release: () => {
      if (isReleased) return;
      isReleased = true;
      held.holders -= 1;
      evictIdle();
    },
  };
}

/** Ready an edition ahead of a press; it stays prepared while there is room for it. */
export async function prepareEdition(
  src: string,
  layout: EditionLayout,
): Promise<void> {
  const hold = holdEdition(src, layout);
  hold.release();
  await hold.edition;
}
