/** A uniform draw in [0, 1) from Web Crypto, for the app's cosmetic and experiment picks. */
export function randomUnit(): number {
  return crypto.getRandomValues(new Uint32Array(1))[0] / 2 ** 32;
}
