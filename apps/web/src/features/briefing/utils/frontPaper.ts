/** The front's paper is read from a band this far in from its left edge, past any border. */
const PAPER_BAND = [0.06, 0.1] as const;

export type Rgb = [number, number, number];

/** The front panel's own paper: the median colour of a band just inside its left border. */
export function frontPaper(front: ImageBitmap): Rgb {
  const { width, height } = front;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context)
    throw new Error("No 2D canvas to read the letter's front panel");
  context.drawImage(front, 0, 0);
  const from = Math.floor(width * PAPER_BAND[0]);
  const to = Math.max(from + 1, Math.floor(width * PAPER_BAND[1]));
  const { data } = context.getImageData(from, 0, to - from, height);
  const channels: number[][] = [[], [], []];
  for (let index = 0; index < data.length; index += 8) {
    for (let channel = 0; channel < 3; channel += 1) {
      channels[channel].push(data[index + channel]);
    }
  }
  return channels.map((values) => {
    values.sort((a, b) => a - b);
    return values[Math.floor(values.length / 2)];
  }) as Rgb;
}
