import { afterEach, describe, expect, it, vi } from "vitest";
import { randomUnit } from "./random";

function drawing(word: number) {
  return vi
    .spyOn(crypto, "getRandomValues")
    .mockImplementation(<T extends ArrayBufferView | null>(array: T): T => {
      (array as unknown as Uint32Array)[0] = word;
      return array;
    });
}

describe("randomUnit", () => {
  afterEach(() => vi.restoreAllMocks());

  it("maps the smallest crypto word to 0", () => {
    drawing(0);
    expect(randomUnit()).toBe(0);
  });

  it("maps the largest crypto word to just under 1", () => {
    drawing(2 ** 32 - 1);
    const draw = randomUnit();
    expect(draw).toBeLessThan(1);
    expect(draw).toBeGreaterThan(0.999_999);
  });

  it("maps the midpoint word to one half", () => {
    drawing(2 ** 31);
    expect(randomUnit()).toBe(0.5);
  });
});
