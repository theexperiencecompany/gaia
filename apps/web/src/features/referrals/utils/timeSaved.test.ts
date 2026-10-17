import { describe, expect, it } from "vitest";

import { formatTimeSaved } from "./timeSaved";

describe("formatTimeSaved", () => {
  it.each([
    [1, "1 minute"],
    [45, "45 minutes"],
    [60, "1 hour"],
    [74, "1 hour"],
    [76, "1.5 hours"],
    [228, "4 hours"],
    [1030, "17 hours"],
  ])("%i minutes reads as %s", (minutes, expected) => {
    expect(formatTimeSaved(minutes)).toBe(expected);
  });
});
