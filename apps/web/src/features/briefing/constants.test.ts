import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { EDITION_ROWS_SHOWN } from "./constants";

const API_CONSTANTS = resolve(
  __dirname,
  "../../../../api/app/constants/briefing.py",
);

describe("EDITION_ROWS_SHOWN", () => {
  it("cuts where the edition's own renderer cuts", () => {
    const declared = readFileSync(API_CONSTANTS, "utf8").match(
      /EDITION_ROWS_SHOWN: Final\[int\] = (\d+)/,
    );

    expect(declared).not.toBeNull();
    expect(EDITION_ROWS_SHOWN).toBe(Number(declared?.[1]));
  });
});
