/**
 * Shared server/runtime configuration facts.
 *
 * Dependency-free (only `electron`) so `server.ts`, window loading, and
 * API-origin resolution can agree on a single source of truth without
 * importing each other — avoiding cross-module import cycles.
 *
 * @module server-config
 */

import { app, type BrowserWindow } from "electron";

/** Port the external Next.js dev server (`nx dev web`) listens on. */
export const DEV_SERVER_PORT = 3000;

/** Origin of the external Next.js dev server. */
export const DEV_SERVER_ORIGIN = `http://localhost:${DEV_SERVER_PORT}`;

/**
 * Whether the app runs against the embedded production server (packaged
 * build) rather than the external `nx dev web` dev server.
 */
export function isProductionServer(): boolean {
  return process.env.NODE_ENV === "production" || app.isPackaged;
}

/**
 * The app route each window was last navigated to via {@link loadAppRoute}.
 *
 * Lives here (not in `load-url.ts`) so the server crash-recovery path can
 * re-navigate each window to its OWN route without importing the window
 * loader — a blanket reload to one route would send the wake-word listener
 * and popup islands to the wrong page and silently break them.
 */
const windowRoutes = new WeakMap<BrowserWindow, string>();

/** Record the app route a window currently displays. */
export function setWindowRoute(win: BrowserWindow, route: string): void {
  windowRoutes.set(win, route);
}

/** The app route a window currently displays, or `undefined` if untracked. */
export function getWindowRoute(win: BrowserWindow): string | undefined {
  return windowRoutes.get(win);
}
