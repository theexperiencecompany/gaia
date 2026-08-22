/**
 * Palette relevance scoring.
 *
 * A term is matched against a field in ranked tiers: exact > prefix >
 * word-boundary prefix > substring > subsequence (with consecutive-run and
 * word-start bonuses). A multi-term query ("wf deploy") requires every term
 * to match somewhere; fields can carry weights so title hits outrank
 * keyword hits.
 */

/** Chars that end a word for boundary bonuses (anything not alnum counts). */
const isBoundary = (text: string, index: number): boolean => {
  if (index <= 0) return true;
  const prev = text[index - 1];
  if (!/\w/.test(prev)) return true;
  // camelCase boundary: lower→upper transition
  return /\p{Ll}/u.test(prev) && /\p{Lu}/u.test(text[index] ?? "");
};

/** Score one query term against one field's text (any case). 0 = no match. */
export function scoreTerm(term: string, field: string): number {
  if (!term || !field) return 0;
  const q = term.toLowerCase();
  const t = field.toLowerCase();

  const at = t.indexOf(q);
  if (at === -1) {
    // Subsequence: every term char must appear in order; reward runs and
    // word starts so "ab" ranks "About Box" above "A x B".
    let score = 0;
    let from = 0;
    let prevMatch = -2;
    for (const ch of q) {
      let found = -1;
      for (let i = from; i < t.length; i++) {
        if (t[i] === ch) {
          found = i;
          break;
        }
      }
      if (found === -1) return 0;
      // Boundary bonuses read the ORIGINAL-cased field — lowercasing would
      // erase exactly the camelCase transitions worth rewarding.
      score += isBoundary(field, found) ? 4 : 1;
      if (found === prevMatch + 1) score += 3;
      prevMatch = found;
      from = found + 1;
    }
    return Math.min(40, score);
  }

  if (t === q) return 100;
  if (at === 0) return 90;
  return isBoundary(field, at) ? 80 : 60;
}

export interface ScoredField {
  text: string | undefined;
  weight?: number;
}

/**
 * Score a whole query against weighted fields.
 *
 * Preferred shape: every term matches inside ONE field — that field's
 * weighted average is added (exact/prefix title hits dominate this way).
 * When no single field holds the whole query but every term matches
 * somewhere across fields (title has "new", keywords have "compose"), the
 * best weighted per-term scores are averaged instead, so multi-term
 * searches spanning an item's fields still surface it. Any unmatched term
 * zeroes the item.
 */
export function scoreFields(query: string, fields: ScoredField[]): number {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return 0;

  let fullFieldTotal = 0;
  const bestPerTerm = new Map<string, { score: number; weight: number }>();

  for (const { text, weight = 1 } of fields) {
    if (!text) continue;
    let sum = 0;
    let allMatch = true;
    for (const term of terms) {
      const s = scoreTerm(term, text);
      // Track each term's best weighted hit across fields even when THIS
      // field won't hold the whole query — the scattered pass needs it.
      if (s > 0) {
        sum += s;
        const prev = bestPerTerm.get(term);
        if (!prev || s * weight > prev.score * prev.weight) {
          bestPerTerm.set(term, { score: s, weight });
        }
      } else {
        allMatch = false;
      }
    }
    if (allMatch) fullFieldTotal += weight * (sum / terms.length);
  }

  if (fullFieldTotal > 0) return fullFieldTotal;

  // Terms are scattered across fields — require each one to exist somewhere.
  if (bestPerTerm.size < terms.length) return 0;
  let total = 0;
  for (const term of terms) {
    const best = bestPerTerm.get(term);
    if (!best) return 0;
    total += best.score * best.weight;
  }
  return total / terms.length;
}
