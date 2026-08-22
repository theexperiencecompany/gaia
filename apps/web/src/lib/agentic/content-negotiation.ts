/**
 * Pure RFC 9110 Accept-header content negotiation for the markdown variants
 * served by the middleware (acceptmarkdown.com v2 protocol). No I/O and no
 * framework-specific types beyond the standard `Request`, so it bundles into
 * the edge runtime and is unit-testable without mocks.
 *
 * Protocol contract implemented here:
 * - The caller only invokes negotiation for URLs that HAVE a markdown
 *   variant, so both `text/html` and `text/markdown` are always available.
 * - Highest q-value wins; an exact media type beats a partial wildcard,
 *   which beats the full wildcard (RFC 9110 §12.5.1 precedence).
 * - Ties prefer `text/markdown`: an agent that explicitly listed it signalled
 *   intent, while wildcard-only clients (browsers, crawlers) get HTML.
 * - Markdown is only ever selected when the header explicitly mentions
 *   `text/markdown`; wildcard-only headers (browsers, crawlers) get HTML.
 * - When neither type is acceptable per the header, the caller must respond
 *   406.
 */

export type NegotiationResult = "markdown" | "html" | "notacceptable";

/**
 * Every response participating in the negotiation — the markdown body, the
 * 406, and HTML pass-throughs — MUST carry this exact Vary value so caches
 * never serve one representation for the other's Accept header.
 */
export const NEGOTIATION_VARY = "Accept, Accept-Encoding";

interface MediaRange {
  /** Lowercase primary type; `"*"` for wildcards. */
  type: string;
  /** Lowercase subtype; `"*"` for wildcards. */
  subtype: string;
  /** Quality value from the `q` parameter; defaults to 1 when absent. */
  q: number;
}

/**
 * Decide how to serve a registry page for this request.
 *
 * Only GET requests participate — callers must fall through untouched for
 * every other method (HEAD included; Next.js serves HEADs itself).
 */
export function negotiate(request: Request): NegotiationResult {
  return negotiateFromAcceptHeader(request.headers.get("accept"));
}

/**
 * Negotiate against a raw Accept header value. Exported separately so tests
 * can exercise header parsing directly.
 */
export function negotiateFromAcceptHeader(
  accept: string | null | undefined,
): NegotiationResult {
  const entries = parseAccept(accept);
  if (!entries) {
    // Missing, blank, or entirely unparseable header: degrade gracefully to
    // the default HTML representation instead of erroring.
    return "html";
  }

  const mdQuality = effectiveQuality(entries, "text", "markdown");
  const htmlQ = effectiveQuality(entries, "text", "html");
  const mdExplicitlyMentioned = entries.some(
    (entry) => entry.type === "text" && entry.subtype === "markdown",
  );

  if (!mdExplicitlyMentioned) {
    // Wildcards or explicit non-markdown types only — never serve markdown.
    if (htmlQ === undefined) {
      // The header has entries but none admits text/html (no wildcard, no
      // text/html): the client accepts neither variant → 406.
      return "notacceptable";
    }
    return htmlQ > 0 ? "html" : "notacceptable";
  }

  // An explicit text/markdown entry always matches exactly, so its quality
  // is defined here; the fallback only satisfies the type checker.
  const mdQ = mdQuality ?? 0;

  if (mdQ <= 0 && (htmlQ ?? 0) <= 0) {
    // Markdown explicitly rejected and HTML unavailable/unacceptable too.
    return "notacceptable";
  }
  if (mdQ <= 0) {
    return "html";
  }
  if ((htmlQ ?? 0) <= 0) {
    return "markdown";
  }
  if (htmlQ !== undefined && htmlQ > mdQ) {
    return "html";
  }
  // mdQ > htmlQ, or equal q — prefer markdown (agent signalled intent).
  return "markdown";
}

/**
 * Parse an Accept header into media ranges with q-values.
 *
 * Returns null when the header is absent/blank or contains no valid range at
 * all (pure garbage), signalling callers to fall back to the default
 * representation. Individual garbage segments are skipped silently — one bad
 * entry must not poison the rest of the header.
 */
function parseAccept(header: string | null | undefined): MediaRange[] | null {
  if (header === null || header === undefined || header.trim() === "") {
    return null;
  }

  const ranges: MediaRange[] = [];
  for (const segment of header.split(",")) {
    const [rawType, ...rawParams] = segment.split(";");
    const parsed = parseTypeRange(rawType);
    if (!parsed) continue;

    let q = 1;
    for (const rawParam of rawParams) {
      const eq = rawParam.indexOf("=");
      if (eq === -1) continue;
      const name = rawParam.slice(0, eq).trim().toLowerCase();
      const value = rawParam.slice(eq + 1).trim();
      if (name !== "q") continue;
      const parsedQ = Number(value);
      // RFC 9110 limits qvalues to 0..1 with up to three decimals.
      if (Number.isFinite(parsedQ) && parsedQ >= 0 && parsedQ <= 1) {
        q = parsedQ;
      } else if (/^\d*\.?\d*$/.test(value) && value !== "") {
        // Numeric but out of range (e.g. q=5): clamp instead of ignoring so
        // sloppy-but-intentional clients still get their preference ordered.
        q = Math.min(Math.max(parsedQ, 0), 1);
      }
      // A malformed non-numeric q is ignored (treated as absent → 1) rather
      // than poisoning the whole entry.
      break;
    }
    ranges.push({ ...parsed, q });
  }

  return ranges.length > 0 ? ranges : null;
}

/** Parse the `type/subtype` portion of a single Accept entry. */
function parseTypeRange(raw: string | undefined): {
  type: string;
  subtype: string;
} | null {
  if (raw === undefined) return null;
  const trimmed = raw.trim().toLowerCase();
  const slash = trimmed.indexOf("/");
  if (slash === -1) return null;
  const type = trimmed.slice(0, slash).trim();
  const subtype = trimmed.slice(slash + 1).trim();
  // Reject empty halves and junk like "text/" or "/html".
  if (type === "" || subtype === "" || !isToken(type) || !isToken(subtype)) {
    return null;
  }
  return { type, subtype };
}

/**
 * RFC 9110 token check, relaxed enough for real-world headers: printable
 * ASCII without separators/control chars. Keeps garbage like `<>` out while
 * tolerating common sloppiness.
 */
function isToken(value: string): boolean {
  return /^[!#$%&'*+\-.^_`|~0-9a-z]+$/.test(value);
}

/**
 * Effective quality for a concrete type under RFC 9110 precedence: the most
 * specific matching range wins (exact type over partial wildcard over full
 * wildcard); within the
 * same specificity the highest q applies (duplicate entries).
 * Returns undefined when no range in the header matches at all.
 */
function effectiveQuality(
  ranges: MediaRange[],
  type: string,
  subtype: string,
): number | undefined {
  let best: number | undefined;
  let bestSpecificity = -1;
  for (const range of ranges) {
    const specificity = range.type === "*" ? 0 : range.subtype === "*" ? 1 : 2;
    if (specificity < bestSpecificity) continue;
    const q = matchQuality(range, type, subtype);
    if (q === null) continue;
    if (specificity > bestSpecificity) {
      bestSpecificity = specificity;
      best = q;
    } else if (q > (best ?? -1)) {
      best = q;
    }
  }
  return best;
}

/** q of `range` for the concrete type if it matches, otherwise null. */
function matchQuality(
  range: MediaRange,
  type: string,
  subtype: string,
): number | null {
  if (range.type === "*") return range.q;
  if (range.type !== type) return null;
  if (range.subtype === "*" || range.subtype === subtype) return range.q;
  return null;
}
