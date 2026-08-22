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

/** Score one query term against one pre-lowercased field. 0 = no match. */
export function scoreTerm(term: string, field: string): number {
  if (!term || !field) return 0;
  const t = field.toLowerCase();

  const at = t.indexOf(term);
  if (at === -1) {
    // Subsequence: every term char must appear in order; reward runs and
    // word starts so "ab" ranks "About Box" above "A x B".
    let score = 0;
    let from = 0;
    let prevMatch = -2;
    for (const ch of term) {
      let found = -1;
      for (let i = from; i < t.length; i++) {
        if (t[i] === ch) {
          found = i;
          break;
        }
      }
      if (found === -1) return 0;
      score += isBoundary(t, found) ? 4 : 1;
      if (found === prevMatch + 1) score += 3;
      prevMatch = found;
      from = found + 1;
    }
    return Math.min(40, score);
  }

  if (t === term) return 100;
  if (at === 0) return 90;
  return isBoundary(t, at) ? 80 : 60;
}

export interface ScoredField {
  text: string | undefined;
  weight?: number;
}

/**
 * Score a whole query against weighted fields. Every whitespace-separated
 * term must match each field's text for that field to count; per-field term
 * scores are averaged so adding terms doesn't inflate a field past a
 * single-term exact match of another.
 */
export function scoreFields(query: string, fields: ScoredField[]): number {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return 0;

  let total = 0;
  for (const { text, weight = 1 } of fields) {
    if (!text) continue;
    let sum = 0;
    let allMatch = true;
    for (const term of terms) {
      const s = scoreTerm(term, text);
      if (s === 0) {
        allMatch = false;
        break;
      }
      sum += s;
    }
    if (allMatch) total += weight * (sum / terms.length);
  }
  return total;
}
