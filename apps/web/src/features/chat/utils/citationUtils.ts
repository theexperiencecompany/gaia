import type { WebResult } from "@/types/features/searchTypes";
import { safeUrl } from "./safeUrl";

/**
 * One citable source in an assistant answer, following the inline-citations
 * contract (https://www.aicss.dev/components/inline-citations): the number
 * written in the text, the label/host shown on hover, and the URL the chip
 * links to.
 */
export interface CitationRef {
  n: number;
  label: string;
  host: string;
  url: string;
}

/** Ordered, URL-deduped citation refs from a message's web results. */
export function citationRefsFromWebResults(
  web: readonly WebResult[] | undefined,
): CitationRef[] {
  const seen = new Set<string>();
  const refs: CitationRef[] = [];
  for (const result of web ?? []) {
    if (!result.url || seen.has(result.url)) continue;
    seen.add(result.url);
    const parsed = safeUrl(result.url);
    refs.push({
      n: refs.length + 1,
      url: result.url,
      label: result.title.trim() || result.url,
      host: parsed?.hostname ?? "",
    });
  }
  return refs;
}

export interface CitationizedText {
  /** Markdown with `[n]` markers replaced by `[n](url)` links where a ref exists. */
  text: string;
  /** The refs actually cited, in order of first appearance in the text. */
  used: CitationRef[];
}

type Segment =
  | { kind: "code"; value: string }
  | { kind: "text"; value: string };

/** A backtick run: start index and the index just past it. */
function nextBacktickRun(
  content: string,
  from: number,
): { start: number; end: number } | null {
  const start = content.indexOf("`", from);
  if (start === -1) return null;
  let end = start;
  while (end < content.length && content[end] === "`") end += 1;
  return { start, end };
}

/**
 * Find the closing run for a code span: a same-or-longer run at a line start
 * for fenced blocks, an exact-length run for inline code. Returns the index
 * just past it, or null when the span is unterminated.
 */
function findCodeClose(
  content: string,
  from: number,
  openRun: number,
  isFence: boolean,
): number | null {
  let cursor = from;
  for (;;) {
    const candidate = nextBacktickRun(content, cursor);
    if (!candidate) return null;
    const candidateRun = candidate.end - candidate.start;
    const atLineStart =
      candidate.start === 0 || content[candidate.start - 1] === "\n";
    if (
      isFence
        ? candidateRun >= openRun && atLineStart
        : candidateRun === openRun
    ) {
      return candidate.end;
    }
    cursor = candidate.end;
  }
}

/**
 * Split markdown into plain-text and backtick-code spans (fenced blocks and
 * inline code), so citation markers inside code are never rewritten.
 */
function splitCodeSpans(content: string): Segment[] {
  const segments: Segment[] = [];
  let textStart = 0;
  let cursor = 0;

  for (;;) {
    const opening = nextBacktickRun(content, cursor);
    if (!opening) break;
    const openRun = opening.end - opening.start;
    const isFence =
      openRun >= 3 &&
      (opening.start === 0 || content[opening.start - 1] === "\n");
    const close = findCodeClose(content, opening.end, openRun, isFence);

    if (opening.start > textStart) {
      segments.push({
        kind: "text",
        value: content.slice(textStart, opening.start),
      });
    }
    if (close === null) {
      segments.push({ kind: "code", value: content.slice(opening.start) });
      break;
    }
    segments.push({ kind: "code", value: content.slice(opening.start, close) });
    textStart = close;
    cursor = close;
  }

  if (textStart < content.length) {
    segments.push({ kind: "text", value: content.slice(textStart) });
  }
  return segments;
}

// A citation marker is [n] that is not part of an adjacent marker pair
// (`[1][2]`) or already markdown-link syntax (`[1](url)`). Like the AICSS
// original, a plain `[n]` in prose counts as a marker; code spans are
// excluded by the splitter, not by the pattern.
const MARKER_PATTERN = /(?<![\]])\[(\d+)\](?!\()/g;

function replaceMarkers(
  value: string,
  refByNumber: ReadonlyMap<number, CitationRef>,
  used: CitationRef[],
  usedNumbers: Set<number>,
): string {
  return value.replace(MARKER_PATTERN, (marker, rawNumber: string) => {
    const ref = refByNumber.get(Number(rawNumber));
    if (!ref) return marker;
    if (!usedNumbers.has(ref.n)) {
      usedNumbers.add(ref.n);
      used.push(ref);
    }
    return `[${ref.n}](${ref.url})`;
  });
}

/**
 * Turn `[n]` citation markers in an answer into real source links so the
 * markdown renderer can style them as chips. Leaves ambiguous markers alone:
 * a marker with no ref, already-written link syntax, or a bracket glued to an
 * identifier (`arr[1]`) stays literal text. Markers inside fenced or inline
 * code are never touched, so code samples keep their brackets.
 */
export function applyCitationLinks(
  content: string,
  refs: readonly CitationRef[],
): CitationizedText {
  const refByNumber = new Map(refs.map((ref) => [ref.n, ref]));
  if (refByNumber.size === 0) return { text: content, used: [] };

  const used: CitationRef[] = [];
  const usedNumbers = new Set<number>();
  let text = "";
  for (const segment of splitCodeSpans(content)) {
    text +=
      segment.kind === "code"
        ? segment.value
        : replaceMarkers(segment.value, refByNumber, used, usedNumbers);
  }
  return { text, used };
}
