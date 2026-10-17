import { afterEach, describe, expect, it, vi } from "vitest";

// A terminal chalk detects as truecolor, so only NO_COLOR can turn colour off.
vi.mock("chalk", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  supportsColor: { level: 3, hasBasic: true, has256: true, has16m: true },
}));

import { terminalColourLevel } from "../../src/ui/header/header-lines.js";
import { logoWidth } from "../../src/ui/header/logo.js";
import {
  type HeaderInput,
  LOGO_TEXT_GAP,
  renderHeader,
} from "../../src/ui/header/render.js";

const ESC = "\u001b";
const SGR = new RegExp(`${ESC}\\[[0-9;]*m`, "g");
const OSC8 = new RegExp(`${ESC}\\]8;;[^${ESC}]*${ESC}\\\\`, "g");

const strip = (line: string): string => line.replace(OSC8, "").replace(SGR, "");

function input(overrides: Partial<HeaderInput> = {}): HeaderInput {
  return {
    size: "small",
    level: 3,
    columns: 120,
    isTTY: true,
    hyperlinks: false,
    version: "0.6.0",
    status: null,
    update: null,
    ...overrides,
  };
}

/** Every SGR parameter list the lines use. */
function sgrParams(lines: string[]): string[] {
  return lines.flatMap((line) =>
    [...line.matchAll(SGR)].map((m) => m[0].slice(2, -1)),
  );
}

describe("renderHeader colour levels", () => {
  it("paints truecolor with the SVG's own fills", () => {
    const params = sgrParams(renderHeader(input({ level: 3 })));
    expect(params).toContain("48;2;15;83;124");
    expect(params).toContain("48;2;5;156;218");
    expect(params).toContain("48;2;2;189;255");
  });

  it("paints 256 colours from 24/38/39 and never the theme-defined 0-15", () => {
    const params = sgrParams(renderHeader(input({ level: 2 })));
    const indices = params.flatMap((p) =>
      [...p.matchAll(/(?:38|48);5;(\d+)/g)].map((m) => Number(m[1])),
    );
    expect(new Set(indices)).toEqual(new Set([24, 38, 39]));
    expect(params.some((p) => p.includes(";2;"))).toBe(false);
  });

  it("paints 16 colours with blue, cyan and bright cyan only", () => {
    const params = sgrParams(renderHeader(input({ level: 1 })));
    const colours = new Set(
      params.filter((p) => /^(3[0-7]|4[0-7]|9[0-7]|10[0-7])$/.test(p)),
    );
    expect(colours).toEqual(new Set(["34", "36", "96", "44", "46", "106"]));
  });

  it("draws an uncoloured silhouette of full and half blocks at level 0", () => {
    const lines = renderHeader(input({ level: 0, size: "large" }));
    expect(lines.join("")).not.toContain(ESC);
    const glyphs = new Set(lines.flatMap((line) => [...line.slice(0, 23)]));
    expect(glyphs).toEqual(new Set([" ", "█", "▀", "▄"]));
    expect(lines).toHaveLength(11);
  });

  it("uses full-colour cells as background spaces, never full-block glyphs", () => {
    const logo = renderHeader(input({ level: 3 })).join("");
    expect(logo).not.toContain("█");
  });
});

describe("terminalColourLevel", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("keeps chalk's level without NO_COLOR", () => {
    vi.stubEnv("NO_COLOR", "");
    expect(terminalColourLevel()).toBe(3);
  });

  it("turns colour off under NO_COLOR, which chalk ignores", () => {
    vi.stubEnv("NO_COLOR", "1");
    expect(terminalColourLevel()).toBe(0);
  });
});

describe("renderHeader layout", () => {
  it("draws the 9-line logo for small and the 11-line one for large", () => {
    expect(renderHeader(input({ size: "small" }))).toHaveLength(9);
    expect(renderHeader(input({ size: "large" }))).toHaveLength(11);
  });

  it("centres the text vertically beside the logo", () => {
    const lines = renderHeader(
      input({ status: { running: false, installed: true } }),
    ).map(strip);
    const textRows = lines.flatMap((line, y) =>
      line.slice(logoWidth("small")).trim() ? [y] : [],
    );
    expect(textRows).toEqual([3, 4, 5]);
    expect(lines[3]?.slice(logoWidth("small") + LOGO_TEXT_GAP)).toBe(
      "GAIA v0.6.0",
    );
  });

  it("falls back to one title line when the logo and text do not fit", () => {
    const tagline = "Your proactive personal assistant";
    const fits = logoWidth("small") + LOGO_TEXT_GAP + tagline.length;
    expect(renderHeader(input({ columns: fits }))).toHaveLength(9);
    const narrow = renderHeader(input({ columns: fits - 1 }));
    expect(narrow.map(strip)).toEqual(["GAIA v0.6.0"]);
  });

  it("falls back to the plain title line when stdout is not a terminal", () => {
    expect(renderHeader(input({ isTTY: false, level: 0 }))).toEqual([
      "GAIA v0.6.0",
    ]);
  });

  it("measures a long status line against the width", () => {
    const status = {
      running: true as const,
      webUrl: "https://a-very-long-subdomain.example.com",
      provider: "OpenRouter",
    };
    const width =
      logoWidth("small") +
      LOGO_TEXT_GAP +
      `● Running at ${status.webUrl} · OpenRouter`.length;
    expect(renderHeader(input({ status, columns: width }))).toHaveLength(9);
    expect(renderHeader(input({ status, columns: width - 1 }))).toHaveLength(1);
  });
});

describe("renderHeader text lines", () => {
  const text = (overrides: Partial<HeaderInput>): string[] =>
    renderHeader(input(overrides))
      .map((line) => strip(line).slice(logoWidth("small") + LOGO_TEXT_GAP))
      .filter(Boolean);

  it("names the version and tagline, with no status line when omitted", () => {
    expect(text({})).toEqual([
      "GAIA v0.6.0",
      "Your proactive personal assistant",
    ]);
  });

  it("says where GAIA runs and on which provider", () => {
    expect(
      text({
        status: {
          running: true,
          webUrl: "http://localhost:3000",
          provider: "OpenRouter",
        },
      }),
    ).toContain("● Running at http://localhost:3000 · OpenRouter");
  });

  it("leaves the provider out when none is serving", () => {
    expect(
      text({
        status: {
          running: true,
          webUrl: "http://localhost:3000",
          provider: null,
        },
      }),
    ).toContain("● Running at http://localhost:3000");
  });

  it("says how to start GAIA when it is not running", () => {
    expect(text({ status: { running: false, installed: true } })).toContain(
      "○ Not running · start it with gaia start",
    );
  });

  it("says how to install GAIA when it is not installed", () => {
    expect(text({ status: { running: false, installed: false } })).toContain(
      "○ Not installed · set it up with gaia up",
    );
  });

  it("links the URL with OSC 8 only where hyperlinks are supported", () => {
    const status = {
      running: true as const,
      webUrl: "http://localhost:3000",
      provider: null,
    };
    const link = `${ESC}]8;;http://localhost:3000${ESC}\\`;
    expect(
      renderHeader(input({ status, hyperlinks: true })).join(""),
    ).toContain(link);
    expect(
      renderHeader(input({ status, hyperlinks: false })).join(""),
    ).not.toContain(`${ESC}]8;;`);
  });

  it("offers the update last", () => {
    expect(
      text({
        status: { running: false, installed: true },
        update: "v0.7.0",
      }).at(-1),
    ).toBe("Update available: v0.7.0 · run gaia update");
  });
});
