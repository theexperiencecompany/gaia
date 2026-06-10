/**
 * Bot utility barrel export.
 *
 * Three layers of reusable logic, ordered from low-level to high-level:
 *
 * 1. formatters - Pure functions that turn data into display strings.
 *    Use these when you need custom response assembly.
 *
 * 2. commands  - Business-logic handlers that call GaiaClient, format results,
 *    and return a ready-to-send string. Bot adapters call these directly.
 *
 * 3. streaming - handleStreamingChat: full streaming lifecycle handler.
 *    Bot adapters provide three callbacks (editMessage, onAuthError, onGenericError)
 *    and the shared function handles throttling, cursor display, and error routing.
 *
 * Text helpers (arg parsing, platform limits, truncation, chunking) live in
 * ./text so sibling modules can import them without a barrel import cycle.
 */

export * from "./commands";
export * from "./formatters";
export * from "./logger";
export * from "./media";
export * from "./streaming";
export * from "./text";
