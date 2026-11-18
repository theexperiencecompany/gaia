import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { BRIEF_ITEM_STATES, EDITION_ROWS_SHOWN } from "./editionLeftOut";

const API_CONSTANTS = resolve(
  __dirname,
  "../../../../../api/app/constants/briefing.py",
);

const API_ITEM_STATES = resolve(
  __dirname,
  "../../../../../api/app/models/brief_item_models.py",
);

describe("BRIEF_ITEM_STATES", () => {
  it("names each item state as the API's voice facts do", () => {
    const block = readFileSync(API_ITEM_STATES, "utf8").match(
      /^_LABELS[^=]*= MappingProxyType\(\s*\{([^}]*)\}/m,
    );
    const declared = Object.fromEntries(
      [...(block?.[1] ?? "").matchAll(/ItemState\.(\w+): "([^"]+)"/g)].map(
        (entry) => [entry[1].toLowerCase(), entry[2]],
      ),
    );

    expect(Object.keys(declared)).toHaveLength(5);
    expect(BRIEF_ITEM_STATES).toEqual(declared);
  });
});

describe("EDITION_ROWS_SHOWN", () => {
  it("cuts where the edition's own renderer cuts", () => {
    const declared = readFileSync(API_CONSTANTS, "utf8").match(
      /EDITION_ROWS_SHOWN: Final\[int\] = (\d+)/,
    );

    expect(declared).not.toBeNull();
    expect(EDITION_ROWS_SHOWN).toBe(Number(declared?.[1]));
  });
});
