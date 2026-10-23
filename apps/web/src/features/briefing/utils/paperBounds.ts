/** Pixels are read from a copy this wide; plenty to find the paper's edges. */
const SAMPLE_WIDTH = 240;
/** The paper colour is read this share of the sheet in from its left edge, past any border. */
const PAPER_INSET_SHARE = 0.06;
const PAPER_SAMPLE_COLUMNS = 4;
/** A sheet on a desk casts a shadow about a sample pixel wide; the crop steps inside it. */
const SHADOW_INSET_SAMPLES = 1;
/** How far a sheet's edge may wander along its length (a tilt, a torn top) before it is content. */
const EDGE_SLANT_SHARE = 0.04;
/** Top and bottom are cut deep along an uneven edge (a torn receipt), leaving no desk between the teeth. */
const END_PERCENTILE = 0.85;
/** The sides keep the widest sheet's edge, so an envelope over a narrower letter keeps its whole border. */
const SIDE_PERCENTILE = 0.15;
/** Within this of the desk's colour in every channel a pixel is desk; a paper vignette stays inside it. */
const DESK_CONTRAST = 64;
/** A sheet set at less than this angle, in radians, is left as drawn. */
const MIN_TILT = 0.002;

/** An image the edition can be read from, with its pixel size. */
export interface EditionSource {
  source: CanvasImageSource;
  width: number;
  height: number;
}

/** Where the paper sits inside the rendered edition, in source pixels, its colour and its tilt. */
export interface PaperSheet {
  x: number;
  y: number;
  width: number;
  height: number;
  /** Mean paper colour, 0..255 per channel. */
  rgb: [number, number, number];
  /** The desk's colour, which fills the corners when the sheet is turned square. */
  desk: [number, number, number];
  /** How far the sheet is turned on its desk, in radians; 0 when it is not on one. */
  tilt: number;
}

interface Pixels {
  data: Uint8ClampedArray;
  width: number;
  height: number;
}

interface EdgePoint {
  along: number;
  line: number;
}

function readPixels({
  source,
  width: fullWidth,
  height: fullHeight,
}: EditionSource): Pixels {
  const width = SAMPLE_WIDTH;
  const height = Math.max(1, Math.round((fullHeight / fullWidth) * width));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context)
    throw new Error("No 2D canvas to read the edition's paper from");
  context.drawImage(source, 0, 0, width, height);
  return {
    data: context.getImageData(0, 0, width, height).data,
    width,
    height,
  };
}

/** Where the desk gives way to the sheet along one side, keeping only the sheet's own edge. */
function edgePoints(
  lines: number,
  span: number,
  isDesk: (line: number, along: number) => boolean,
): EdgePoint[] {
  const points: EdgePoint[] = [];
  for (let along = 0; along < span; along += 1) {
    for (let line = 0; line < lines; line += 1) {
      if (!isDesk(line, along)) {
        points.push({ along, line });
        break;
      }
    }
  }
  if (points.length === 0) return points;
  const outermost = Math.min(...points.map((point) => point.line));
  const slant = Math.ceil(lines * EDGE_SLANT_SHARE);
  return points.filter((point) => point.line <= outermost + slant);
}

/** The crop line for one side, at the given depth through its uneven edge. */
function cropDepth(points: EdgePoint[], percentile: number): number {
  if (points.length === 0) return 0;
  const lines = points.map((point) => point.line).sort((a, b) => a - b);
  return lines[Math.floor((lines.length - 1) * percentile)];
}

/** The angle of a sheet's top edge from level, by least squares over its edge points. */
function edgeAngle(points: EdgePoint[]): number {
  if (points.length < 2) return 0;
  const meanAlong = points.reduce((sum, p) => sum + p.along, 0) / points.length;
  const meanLine = points.reduce((sum, p) => sum + p.line, 0) / points.length;
  let covariance = 0;
  let variance = 0;
  for (const point of points) {
    covariance += (point.along - meanAlong) * (point.line - meanLine);
    variance += (point.along - meanAlong) ** 2;
  }
  return variance === 0 ? 0 : Math.atan(covariance / variance);
}

/** Find the paper inside the edition: an edition drawn on a desk keeps the desk outside these bounds. */
export function findPaper(edition: EditionSource): PaperSheet {
  const pixels = readPixels(edition);
  const { width, height, data } = pixels;
  const at = (x: number, y: number) => (y * width + x) * 4;
  const isDeskAt = (index: number) =>
    [0, 1, 2].every(
      (channel) =>
        Math.abs(data[index + channel] - data[channel]) <= DESK_CONTRAST,
    );

  const left = cropDepth(
    edgePoints(width, height, (line, along) => isDeskAt(at(line, along))),
    SIDE_PERCENTILE,
  );
  const right = cropDepth(
    edgePoints(width, height, (line, along) =>
      isDeskAt(at(width - 1 - line, along)),
    ),
    SIDE_PERCENTILE,
  );
  const topEdge = edgePoints(height, width, (line, along) =>
    isDeskAt(at(along, line)),
  );
  const top = cropDepth(topEdge, END_PERCENTILE);
  const bottom = cropDepth(
    edgePoints(height, width, (line, along) =>
      isDeskAt(at(along, height - 1 - line)),
    ),
    END_PERCENTILE,
  );

  const rgb: [number, number, number] = [0, 0, 0];
  let samples = 0;
  const sampleFrom =
    left + Math.round((width - left - right) * PAPER_INSET_SHARE);
  for (let y = top; y < height - bottom; y += 1) {
    for (let dx = 0; dx < PAPER_SAMPLE_COLUMNS; dx += 1) {
      const index = at(Math.min(width - 1, sampleFrom + dx), y);
      rgb[0] += data[index];
      rgb[1] += data[index + 1];
      rgb[2] += data[index + 2];
      samples += 1;
    }
  }
  const paper = rgb.map((sum) => Math.round(sum / Math.max(1, samples))) as [
    number,
    number,
    number,
  ];
  const desk: [number, number, number] = [data[0], data[1], data[2]];

  // A desk runs one flat colour along the whole edge and is clearly unlike the
  // paper; an edge that is the sheet itself keeps its full margin.
  const edgeIsFlat =
    Array.from({ length: width }, (_, x) => at(x, 0)).every(isDeskAt) &&
    Array.from({ length: height }, (_, y) => at(0, y)).every(isDeskAt);
  const isOnADesk =
    edgeIsFlat &&
    paper.some(
      (channel, index) => Math.abs(channel - desk[index]) > DESK_CONTRAST,
    );
  if (!isOnADesk) {
    return {
      x: 0,
      y: 0,
      width: edition.width,
      height: edition.height,
      rgb: paper,
      desk,
      tilt: 0,
    };
  }
  const tilt = edgeAngle(topEdge);
  const inset = SHADOW_INSET_SAMPLES;
  const scale = edition.width / width;
  return {
    x: (left + inset) * scale,
    y: (top + inset) * scale,
    width: (width - left - right - 2 * inset) * scale,
    height: (height - top - bottom - 2 * inset) * scale,
    rgb: paper,
    desk,
    tilt: Math.abs(tilt) < MIN_TILT ? 0 : tilt,
  };
}

/** Turn a tilted sheet square on its desk, so a rectangular crop takes all of its border and none of the desk. */
export function straighten(
  image: HTMLImageElement,
  sheet: PaperSheet,
): EditionSource {
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("No 2D canvas to straighten the edition on");
  context.fillStyle = `rgb(${sheet.desk.join(", ")})`;
  context.fillRect(0, 0, width, height);
  context.translate(width / 2, height / 2);
  context.rotate(-sheet.tilt);
  context.drawImage(image, -width / 2, -height / 2);
  return { source: canvas, width, height };
}
