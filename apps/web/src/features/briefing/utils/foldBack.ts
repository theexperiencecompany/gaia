/** The strip drawn for a folded-under panel's showing edge, in bitmap pixels. */
const FOLD_STRIP_HEIGHT = 20;
/** A pixel within this of the paper colour in every channel is bare paper, not border. */
const PAPER_MATCH = 28;
/** Border bands thicker than this share of the panel are content, not border. */
const MAX_BORDER_SHARE = 0.12;
/** The front's paper is read from a band this far in from its left edge, past any border. */
const PAPER_BAND = [0.06, 0.1] as const;
/** The side borders are read from a row this far down the front panel. */
const BORDER_ROW_SHARE = 0.6;

export type Rgb = [number, number, number];

/** The front panel's own paper: the median colour of a band just inside its left border. */
function paperOf(data: Uint8ClampedArray, width: number, height: number): Rgb {
  const channels: number[][] = [[], [], []];
  const from = Math.floor(width * PAPER_BAND[0]);
  const to = Math.max(from + 1, Math.floor(width * PAPER_BAND[1]));
  for (let y = 0; y < height; y += 2) {
    for (let x = from; x < to; x += 2) {
      const index = (y * width + x) * 4;
      for (let channel = 0; channel < 3; channel += 1) {
        channels[channel].push(data[index + channel]);
      }
    }
  }
  return channels.map((values) => {
    values.sort((a, b) => a - b);
    return values[Math.floor(values.length / 2)];
  }) as Rgb;
}

/** How many pixels in from one edge the border runs before bare paper begins. */
function borderDepth(
  steps: number,
  isPaper: (step: number) => boolean,
): number {
  const limit = Math.floor(steps * MAX_BORDER_SHARE);
  for (let step = 0; step < limit; step += 1) {
    if (isPaper(step)) return step;
  }
  return 0;
}

/**
 * The showing edge of a panel folded under the front one, cut from the front
 * panel itself: its bare paper with the side borders carried down, so it reads
 * as the same sheet and never shows content.
 */
export interface FoldBack {
  strip: ImageBitmap;
  /** The front panel's own paper colour. */
  paper: Rgb;
}

export async function foldBackFrom(front: ImageBitmap): Promise<FoldBack> {
  const { width, height } = front;
  const reader = document.createElement("canvas");
  reader.width = width;
  reader.height = height;
  const readContext = reader.getContext("2d", { willReadFrequently: true });
  if (!readContext) {
    throw new Error("No 2D canvas to read the letter's front panel");
  }
  readContext.drawImage(front, 0, 0);
  const { data } = readContext.getImageData(0, 0, width, height);
  const paper = paperOf(data, width, height);
  const isPaperAt = (x: number, y: number) => {
    const index = (y * width + x) * 4;
    return [0, 1, 2].every(
      (channel) =>
        Math.abs(data[index + channel] - paper[channel]) <= PAPER_MATCH,
    );
  };
  const row = Math.floor(height * BORDER_ROW_SHARE);
  const left = borderDepth(width, (x) => isPaperAt(x, row));
  const right = borderDepth(width, (x) => isPaperAt(width - 1 - x, row));

  const strip = document.createElement("canvas");
  strip.width = width;
  strip.height = FOLD_STRIP_HEIGHT;
  const context = strip.getContext("2d");
  if (!context)
    throw new Error("No 2D canvas to draw the letter's folded panel");
  context.fillStyle = `rgb(${paper.join(", ")})`;
  context.fillRect(0, 0, width, FOLD_STRIP_HEIGHT);
  const band = Math.min(FOLD_STRIP_HEIGHT, height - row);
  // The side borders run on down the folded panels, cut from the front's own sides.
  if (left) {
    context.drawImage(front, 0, row, left, band, 0, 0, left, FOLD_STRIP_HEIGHT);
  }
  if (right) {
    context.drawImage(
      front,
      width - right,
      row,
      right,
      band,
      width - right,
      0,
      right,
      FOLD_STRIP_HEIGHT,
    );
  }
  return { strip: await createImageBitmap(strip), paper };
}
