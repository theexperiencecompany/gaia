import { execFileSync, spawnSync } from "node:child_process";
import * as fs from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  ANSI16_TERM,
  APPLE_TERMINAL,
  colourLevel,
  TRUECOLOR_COLORTERMS,
  TRUECOLOR_PROGRAMS,
  TRUECOLOR_TERM,
} from "../../src/lib/colour-level.js";

const INSTALLER = fileURLToPath(new URL("../../install.sh", import.meta.url));
const UNSET = "-";

/** install.sh's colour_level function, as written there. */
function installerColourLevel(): string {
  const source = fs.readFileSync(INSTALLER, "utf8");
  const fn = source.match(/^colour_level\(\) \{\n[\s\S]*?\n\}$/m)?.[0];
  if (!fn) throw new Error("install.sh has no colour_level function");
  return fn;
}

/** TERM values that hit each alternative of a TERM rule, so a new one cannot go untested. */
function termSamples(rule: RegExp): string[] {
  return rule.source.split("|").flatMap((alternative) => {
    const body = alternative.replace(/^\^/, "").replace(/\$$/, "");
    const head = alternative.startsWith("^") ? "" : "x";
    const tail = alternative.endsWith("$") ? "" : "x";
    const bodies = body.includes("(color)?")
      ? [body.replace("(color)?", "color"), body.replace("(color)?", "")]
      : [body];
    return bodies.map((b) => head + b + tail);
  });
}

const TERMS = [
  UNSET,
  "",
  "dumb",
  "vt52",
  ...termSamples(TRUECOLOR_TERM),
  ...termSamples(ANSI16_TERM),
];
const COLORTERMS = [UNSET, "", ...TRUECOLOR_COLORTERMS, "yes"];
const PROGRAMS = [UNSET, APPLE_TERMINAL, ...TRUECOLOR_PROGRAMS, "Hyper"];
const FORCE_COLORS = [UNSET, "", "true", "false", "0", "1", "2", "3"];
const NO_COLORS = [UNSET, "", "1"];
const TTYS = [true, false];

interface Case {
  isTTY: boolean;
  env: Record<string, string>;
}

function cases(): Case[] {
  const out: Case[] = [];
  for (const isTTY of TTYS)
    for (const FORCE_COLOR of FORCE_COLORS)
      for (const NO_COLOR of NO_COLORS)
        for (const TERM of TERMS)
          for (const COLORTERM of COLORTERMS)
            for (const TERM_PROGRAM of PROGRAMS) {
              const vars = {
                FORCE_COLOR,
                NO_COLOR,
                TERM,
                COLORTERM,
                TERM_PROGRAM,
              };
              const env = Object.fromEntries(
                Object.entries(vars).filter(([, v]) => v !== UNSET),
              );
              out.push({ isTTY, env });
            }
  return out;
}

const VARS = ["FORCE_COLOR", "NO_COLOR", "TERM", "COLORTERM", "TERM_PROGRAM"];

/** Every case through install.sh's function in one sh, a level per line. */
function installerLevels(all: Case[]): number[] {
  const driver = `${installerColourLevel()}
while IFS='|' read -r tty ${VARS.join(" ")}; do
${VARS.map((v) => `  [ "$${v}" = "${UNSET}" ] && unset ${v}`).join("\n")}
  colour_level "$tty"
  echo "$COLOUR_LEVEL"
done
`;
  const input = all
    .map(({ isTTY, env }) =>
      [isTTY ? "tty" : "", ...VARS.map((v) => env[v] ?? UNSET)].join("|"),
    )
    .join("\n");
  const out = execFileSync("sh", ["-c", driver], {
    input: `${input}\n`,
    encoding: "utf8",
    env: {},
  });
  return out.trim().split("\n").map(Number);
}

describe("install.sh colour_level", () => {
  it("picks the CLI's colour level for every environment", () => {
    const all = cases();
    const shell = installerLevels(all);
    const disagreements = all.flatMap((c, i) => {
      const cli = colourLevel({
        env: c.env,
        isTTY: c.isTTY,
        platform: "linux",
      });
      return cli === shell[i] ? [] : [{ ...c, cli, installer: shell[i] }];
    });
    expect(shell).toHaveLength(all.length);
    expect(disagreements.slice(0, 5)).toEqual([]);
  });

  it("keeps truecolor over SSH, where TERM arrives and COLORTERM does not", () => {
    const [level] = installerLevels([
      { isTTY: true, env: { TERM: "xterm-256color" } },
    ]);
    expect(level).toBe(3);
  });

  it("refuses a FORCE_COLOR it does not know, as the CLI does", () => {
    const run = spawnSync(
      "sh",
      ["-c", `${installerColourLevel()}\ncolour_level tty\necho reached`],
      { encoding: "utf8", env: { FORCE_COLOR: "yes" } },
    );
    expect(run.status).toBe(1);
    expect(run.stdout).not.toContain("reached");
    expect(run.stderr).toContain('FORCE_COLOR="yes"');
    expect(() =>
      colourLevel({
        env: { FORCE_COLOR: "yes" },
        isTTY: true,
        platform: "linux",
      }),
    ).toThrow();
  });
});
