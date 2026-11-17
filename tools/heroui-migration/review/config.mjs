/** Constants every review step shares. stack.sh mirrors the ports. */
import { createHash } from "node:crypto";
import { join } from "node:path";

export const REVIEW_USER = "review@gaia.local";
export const ONBOARDING_USER = "onboarding@gaia.local";
/** The seeded user's zone and the capture browser's, so server- and client-rendered dates agree. */
export const TIMEZONE = "Asia/Kolkata";
export const LOCALE = "en-US";

export const API_BASE = "http://localhost:8100/api/v1";
export const WEB_BASE = { before: "http://localhost:3210", after: "http://localhost:3211" };

/** Captures are pinned to one hour after the seed, so relative times read the same on every run. */
export const CLOCK_OFFSET_MS = 60 * 60 * 1000;

export const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900, deviceScaleFactor: 1, isMobile: false, hasTouch: false },
  { name: "mobile", width: 390, height: 844, deviceScaleFactor: 1, isMobile: true, hasTouch: true },
];

/** Full-page shots are cut at this height; Chromium tiles past ~16k px and the tail is footer. */
export const MAX_PAGE_HEIGHT = 12_000;

export const DEFAULT_OUT = join(process.env.HOME ?? ".", "v3review", "out");

/** A state's identity across builds and runs: what it does, to which role + accessible name. */
export const stateId = (s) => (s ? `${s.kind}|${s.role}|${s.name}|${s.nth}` : "base");

/** The PNG name of one target + state, stable across builds and runs. */
export const fileOf = (key, sid) => {
  const slug = (key === "/" ? "root" : key.replace(/^\//, "").replace(/[^a-zA-Z0-9]+/g, "_")).slice(0, 80);
  return sid === "base" ? `${slug}.png` : `${slug}__${createHash("sha1").update(sid).digest("hex").slice(0, 10)}.png`;
};

export const AREAS = ["marketing", "chat", "todos", "calendar", "workflows", "settings", "onboarding", "desktop popup", "auth", "app"];
