// Shared exception-noise filter for the client observability sinks (PostHog +
// Sentry). Crawlers and browser extensions inject inline scripts into our
// statically-generated SEO pages and throw errors our code cannot produce
// (e.g. `TypeError: Cannot read properties of null (reading 'document')` from
// an injected `HTMLDocument.c` handler). Because the only stack frame's
// filename is the page URL rather than a bundle, error tracking fingerprints
// each crawled page as a brand-new issue.
//
// The predicate below keeps only exceptions that touch a GAIA-authored bundle
// (`/_next/static/`) and drops well-known browser/extension noise. Genuine
// first-party errors — ChunkLoadError, minified React errors — always carry
// bundle frame filenames and pass through unchanged.

import type { ErrorEvent as SentryErrorEvent } from "@sentry/nextjs";
import type { BeforeSendFn, CaptureResult } from "posthog-js";

/**
 * Path segment every GAIA browser bundle is served under. A stack frame with a
 * filename containing this segment is our own code; anything else is foreign.
 */
const APP_ASSET_PATH = "/_next/static/";

/**
 * Exception messages thrown by browsers, extensions, or third-party scripts
 * that are never actionable from our code. Substrings match anywhere in the
 * message; regexes cover variants (different origins, property names, browser
 * wordings). Shared with Sentry's native `ignoreErrors` option so both sinks
 * agree.
 */
export const IGNORED_EXCEPTION_MESSAGES: readonly (string | RegExp)[] = [
  // Opaque cross-origin script errors — no usable stack, not ours.
  "Script error.",
  // Benign ResizeObserver notification-loop warnings surfaced as errors
  // ("...completed with undelivered notifications." and "...loop limit exceeded").
  /ResizeObserver loop/,
  // Cross-origin frame access from injected / third-party scripts.
  /Blocked a frame with origin .* from accessing a cross-origin frame/,
  // Firefox cross-origin property access denial.
  /Permission denied to access property/,
];

/**
 * URL schemes for browser-extension code. Frames served from these never
 * belong to GAIA. Shared with Sentry's native `denyUrls` option.
 */
export const EXTENSION_URL_PATTERNS: readonly RegExp[] = [
  /^chrome-extension:\/\//,
  /^moz-extension:\/\//,
  /^safari-(web-)?extension:\/\//,
  /^webkit-masked-url:/,
];

/** An exception reduced to the fields the drop predicate needs. */
interface NormalizedException {
  message: string;
  frameFilenames: string[];
}

function messageIsIgnored(message: string): boolean {
  return IGNORED_EXCEPTION_MESSAGES.some((pattern) =>
    typeof pattern === "string"
      ? message.includes(pattern)
      : pattern.test(message),
  );
}

/**
 * Returns true when an exception should be dropped before it reaches a sink.
 * An exception is kept only when it is not a known-benign class and at least
 * one of its stack frames originates from our own `/_next/static/` bundle.
 */
function shouldDropException(
  exceptions: readonly NormalizedException[],
): boolean {
  // 1. Known browser / extension noise — drop regardless of stack.
  if (exceptions.some((ex) => messageIsIgnored(ex.message))) return true;

  // 2. Allowlist: keep only errors that touch a GAIA bundle frame. Injected
  //    inline handlers, extension scripts, and stackless cross-origin errors
  //    never do, so they are dropped.
  const touchesAppBundle = exceptions.some((ex) =>
    ex.frameFilenames.some((filename) => filename.includes(APP_ASSET_PATH)),
  );
  return !touchesAppBundle;
}

// --- PostHog ($exception event) ---------------------------------------------

const POSTHOG_EXCEPTION_EVENT = "$exception";
const POSTHOG_EXCEPTION_LIST_PROP = "$exception_list";

/** Client-side shape of a `$exception_list` entry at `before_send` time. */
interface PosthogException {
  value?: string | null;
  stacktrace?: { frames?: Array<{ filename?: string | null }> | null } | null;
}

/**
 * PostHog `before_send` hook. Passes every non-exception event through
 * untouched and drops exceptions that don't originate from our bundle.
 */
export const filterExceptionBeforeSend: BeforeSendFn = (
  result: CaptureResult | null,
): CaptureResult | null => {
  if (!result || result.event !== POSTHOG_EXCEPTION_EVENT) return result;

  const list = result.properties[POSTHOG_EXCEPTION_LIST_PROP] as
    | PosthogException[]
    | undefined;
  if (!list?.length) return result;

  const normalized: NormalizedException[] = list.map((ex) => ({
    message: ex.value ?? "",
    frameFilenames: (ex.stacktrace?.frames ?? [])
      .map((frame) => frame.filename)
      .filter((filename): filename is string => typeof filename === "string"),
  }));

  return shouldDropException(normalized) ? null : result;
};

// --- Sentry (error event) ----------------------------------------------------

/**
 * Sentry `beforeSend` hook. Mirrors the PostHog predicate so both sinks agree;
 * complements Sentry's native `ignoreErrors` / `denyUrls` by enforcing the
 * bundle-frame allowlist those options cannot express.
 */
export function filterSentryEvent(
  event: SentryErrorEvent,
): SentryErrorEvent | null {
  const values = event.exception?.values;
  if (!values?.length) return event;

  const normalized: NormalizedException[] = values.map((ex) => ({
    message: ex.value ?? "",
    frameFilenames: (ex.stacktrace?.frames ?? [])
      .map((frame) => frame.filename)
      .filter((filename): filename is string => typeof filename === "string"),
  }));

  return shouldDropException(normalized) ? null : event;
}
