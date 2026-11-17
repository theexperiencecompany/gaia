/** Every third-party script, frame and stylesheet the code loads is allowed by the site CSP, so a new origin cannot ship blocked. */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

type Directive = "script-src" | "frame-src" | "style-src";
type LoadSite = { file: string; directive: Directive; url: string };

const WEB_ROOT = process.cwd();
const SOURCE_ROOTS = ["src", "instrumentation-client.ts"];
const SOURCE_FILE = /\.(ts|tsx)$/;
const TEST_FILE = /(\.test\.tsx?$|\/__tests__\/)/;

// The tag up to its src, with no other tag in between; group 3 is a literal, group 4 an identifier.
const ELEMENT_SRC =
  /<(iframe|Script|script)\b[^<]*?\bsrc=\{?\s*(?:(["'`])(.*?)\2|([A-Za-z_$][\w$]*)\s*\})/g;
const ELEMENT_DIRECTIVE: Record<string, Directive> = {
  iframe: "frame-src",
  Script: "script-src",
  script: "script-src",
};
// An element made with document.createElement, whose URL is assigned later.
const CREATED_ELEMENT =
  /\b(\w+)\s*=\s*document\.createElement\("(link|script|iframe)"\)/g;
const CREATED_DIRECTIVE: Record<string, Directive> = {
  link: "style-src",
  script: "script-src",
  iframe: "frame-src",
};
const INTERPOLATION = /^\$\{([A-Z_]+)\}/;

function sourceFiles(entry: string): string[] {
  const full = path.join(WEB_ROOT, entry);
  if (SOURCE_FILE.test(entry)) return [full];
  return readdirSync(full, { recursive: true, encoding: "utf8" })
    .filter((f) => SOURCE_FILE.test(f) && !TEST_FILE.test(`/${f}`))
    .map((f) => path.join(full, f));
}

/** Every https URL a local variable is assigned, for `src={embedSrc}`. */
function assignedUrls(source: string, name: string): string[] {
  const assignment = new RegExp(
    `\\b${name}\\s*=\\s*(["'\`])(https://[^"'\`]+)\\1`,
    "g",
  );
  return [...source.matchAll(assignment)].map((m) => m[2]);
}

function resolveUrl(raw: string, origins: Record<string, string>): string {
  const constant = INTERPOLATION.exec(raw)?.[1];
  if (!constant) return raw;
  const value = origins[constant];
  if (!value) {
    throw new Error(
      `${raw} interpolates ${constant}, which third-party-origins.mjs does not export`,
    );
  }
  return raw.replace(INTERPOLATION, value);
}

function loadSites(origins: Record<string, string>): LoadSite[] {
  const sites: LoadSite[] = [];
  for (const file of SOURCE_ROOTS.flatMap(sourceFiles)) {
    const source = readFileSync(file, "utf8");
    const rel = path.relative(WEB_ROOT, file);
    for (const m of source.matchAll(ELEMENT_SRC)) {
      const directive = ELEMENT_DIRECTIVE[m[1]];
      const identifier = m[4];
      const urls = !identifier
        ? [m[3]]
        : origins[identifier]
          ? [origins[identifier]]
          : assignedUrls(source, identifier);
      for (const raw of urls) {
        const url = resolveUrl(raw, origins);
        if (url.startsWith("https://"))
          sites.push({ file: rel, directive, url });
      }
    }
    for (const [, name, tag] of source.matchAll(CREATED_ELEMENT)) {
      const urlAssignment = new RegExp(
        `\\b${name}\\.(?:href|src)\\s*=\\s*(["'\`])(https://[^"'\`]+)\\1`,
        "g",
      );
      for (const m of source.matchAll(urlAssignment)) {
        sites.push({ file: rel, directive: CREATED_DIRECTIVE[tag], url: m[2] });
      }
    }
  }
  return sites;
}

/** CSP host-source matching: exact origin, or a *. wildcard over subdomains. */
function allows(sources: string[], url: string): boolean {
  const { origin, hostname } = new URL(url);
  return sources.some((source) => {
    if (source === "https:") return true;
    if (source.startsWith("https://*.")) {
      return hostname.endsWith(source.slice("https://*".length));
    }
    return source === origin;
  });
}

let directives: Map<string, string[]>;
let sites: LoadSite[];

beforeAll(async () => {
  const origins = (await import("../../third-party-origins.mjs")) as Record<
    string,
    string
  >;
  const { NEXT_SECURITY_HEADER_RULES } = await import(
    "../../security-headers.mjs"
  );
  const policy = NEXT_SECURITY_HEADER_RULES[0].headers.find(
    ({ key }) => key === "Content-Security-Policy-Report-Only",
  )?.value;
  if (!policy) throw new Error("the site rule carries no CSP");
  directives = new Map(
    policy.split(";").map((directive) => {
      const [name, ...sources] = directive.trim().split(/\s+/);
      return [name, sources];
    }),
  );
  sites = loadSites(origins);
});

describe("CSP origins", () => {
  it("finds the load sites it guards", () => {
    const found = sites.map(
      ({ directive, url }) => `${directive} ${new URL(url).origin}`,
    );
    expect(found).toEqual(
      expect.arrayContaining([
        "frame-src https://status.heygaia.io",
        "frame-src https://www.youtube.com",
        "frame-src https://player.vimeo.com",
        "script-src https://as.heygaia.io",
        "style-src https://cdn.jsdelivr.net",
      ]),
    );
  });

  it("allows every script, frame and stylesheet origin the code loads", () => {
    const blocked = sites
      .filter(
        ({ directive, url }) => !allows(directives.get(directive) ?? [], url),
      )
      .map(
        ({ file, directive, url }) =>
          `${file}: ${directive} does not allow ${url}`,
      );
    expect(blocked).toEqual([]);
  });
});
