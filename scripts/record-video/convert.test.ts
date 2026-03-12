import { describe, it, expect } from "vitest";
import { QUALITY_PRESET } from "./convert.js";

describe("QUALITY_PRESET", () => {
  it("high quality uses crf 18", () => {
    expect(QUALITY_PRESET.high.crf).toBe(18);
  });

  it("medium quality uses crf 23", () => {
    expect(QUALITY_PRESET.medium.crf).toBe(23);
  });

  it("low quality uses crf 32", () => {
    expect(QUALITY_PRESET.low.crf).toBe(32);
  });

  it("all presets have a preset string", () => {
    expect(typeof QUALITY_PRESET.high.preset).toBe("string");
    expect(typeof QUALITY_PRESET.medium.preset).toBe("string");
    expect(typeof QUALITY_PRESET.low.preset).toBe("string");
  });

  it("higher quality has lower crf value", () => {
    expect(QUALITY_PRESET.high.crf).toBeLessThan(QUALITY_PRESET.medium.crf);
    expect(QUALITY_PRESET.medium.crf).toBeLessThan(QUALITY_PRESET.low.crf);
  });
});
