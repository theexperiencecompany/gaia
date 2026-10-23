/** Pixels are read from a copy this wide; plenty to find the paper's edges. */
const SAMPLE_WIDTH = 240;
/** A channel differing by more than this from the edge is content (the renderer's own trim threshold). */
const BACKDROP_THRESHOLD = 24;
/** The paper colour is read this share of the sheet in from its left edge, past any border. */
const PAPER_INSET_SHARE = 0.06;
const PAPER_SAMPLE_COLUMNS = 4;
/** A sheet on a desk casts a shadow a couple of sample pixels wide; the crop steps inside it. */
const SHADOW_INSET_SAMPLES = 5;
/** A desk differs from the paper by more than this in some channel; a paper vignette does not. */
const DESK_CONTRAST = 64;

/** Where the paper sits inside the rendered edition, in source pixels, and its colour. */
export interface PaperSheet {
  x: number;
  y: number;
  width: number;
  height: number;
  /** Mean paper colour, 0..255 per channel. */
  rgb: [number, number, number];
}

interface Pixels {
  data: Uint8ClampedArray;
  width: number;
  height: number;
}

function readPixels(image: HTMLImageElement): Pixels {
  const width = SAMPLE_WIDTH;
  const height = Math.max(
    1,
    Math.round((image.naturalHeight / image.naturalWidth) * width),
  );
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context)
    throw new Error("No 2D canvas to read the edition's paper from");
  context.drawImage(image, 0, 0, width, height);
  return {
    data: context.getImageData(0, 0, width, height).data,
    width,
    height,
  };
}

function differs(pixels: Pixels, a: number, b: number): boolean {
  const { data } = pixels;
  return (
    Math.abs(data[a] - data[b]) > BACKDROP_THRESHOLD ||
    Math.abs(data[a + 1] - data[b + 1]) > BACKDROP_THRESHOLD ||
    Math.abs(data[a + 2] - data[b + 2]) > BACKDROP_THRESHOLD
  );
}

/** How many lines from one side match that side's outermost line: the backdrop around the paper. */
function backdropRun(
  pixels: Pixels,
  lines: number,
  span: number,
  offset: (line: number, along: number) => number,
): number {
  for (let line = 0; line < lines; line += 1) {
    for (let along = 0; along < span; along += 1) {
      if (differs(pixels, offset(line, along), offset(0, along))) return line;
    }
  }
  return 0;
}

/** Find the paper inside the edition: an edition drawn on a desk keeps the desk outside these bounds. */
export function findPaper(image: HTMLImageElement): PaperSheet {
  const pixels = readPixels(image);
  const { width, height } = pixels;
  const at = (x: number, y: number) => (y * width + x) * 4;
  const left = backdropRun(pixels, width, height, (line, along) =>
    at(line, along),
  );
  const right = backdropRun(pixels, width, height, (line, along) =>
    at(width - 1 - line, along),
  );
  const top = backdropRun(pixels, height, width, (line, along) =>
    at(along, line),
  );
  const bottom = backdropRun(pixels, height, width, (line, along) =>
    at(along, height - 1 - line),
  );

  const rgb: [number, number, number] = [0, 0, 0];
  let samples = 0;
  const sampleFrom =
    left + Math.round((width - left - right) * PAPER_INSET_SHARE);
  for (let y = top; y < height - bottom; y += 1) {
    for (let dx = 0; dx < PAPER_SAMPLE_COLUMNS; dx += 1) {
      const index = at(Math.min(width - 1, sampleFrom + dx), y);
      rgb[0] += pixels.data[index];
      rgb[1] += pixels.data[index + 1];
      rgb[2] += pixels.data[index + 2];
      samples += 1;
    }
  }

  const paper = rgb.map((sum) => Math.round(sum / Math.max(1, samples))) as [
    number,
    number,
    number,
  ];
  const corner = [pixels.data[0], pixels.data[1], pixels.data[2]];
  const isOnADesk = paper.some(
    (channel, index) => Math.abs(channel - corner[index]) > DESK_CONTRAST,
  );
  if (!isOnADesk) {
    // The edge is the paper itself: its margin is part of the sheet, not a backdrop.
    return {
      x: 0,
      y: 0,
      width: image.naturalWidth,
      height: image.naturalHeight,
      rgb: paper,
    };
  }
  // Step past the sheet's own drop shadow onto the desk-free paper.
  const inset = SHADOW_INSET_SAMPLES;
  const scale = image.naturalWidth / width;
  return {
    x: (left + inset) * scale,
    y: (top + inset) * scale,
    width: (width - left - right - 2 * inset) * scale,
    height: (height - top - bottom - 2 * inset) * scale,
    rgb: paper,
  };
}
