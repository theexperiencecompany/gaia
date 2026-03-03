/**
 * Window Management — barrel export.
 *
 * Re-exports splash and main window utilities so consumers
 * can import from `./windows` directly.
 *
 * @module windows
 */

export {
  consumePendingDeepLink,
  createMainWindow,
  getMainWindow,
  setPendingDeepLink,
  showMainWindow,
} from "./main";
export {
  closeSplashWindow,
  createSplashWindow,
  isSplashAlive,
} from "./splash";
