/**
 * Token totals turned into things a person can picture.
 *
 * Every constant below is a stated, checkable average rather than a vibe, and
 * each line hides itself once its number stops being interesting — "0.02
 * novels" tells you nothing, so it is skipped rather than rounded into a lie.
 */

/** The usual English rule of thumb: one token is about three quarters of a word. */
const WORDS_PER_TOKEN = 0.75;

/** A mass-market novel, rounded to the nearest ten thousand. */
const WORDS_PER_NOVEL = 80_000;
/** Roughly thirty novels stood side by side fills one packed shelf. */
const NOVELS_PER_SHELF = 30;
/** Words an average person actually speaks in a day (Mehl et al., 2007). */
const WORDS_SPOKEN_PER_DAY = 16_000;
/** Silent reading speed for adult non-fiction (Brysbaert, 2019). */
const WORDS_READ_PER_MINUTE = 238;
/** A competent touch typist, sustained. */
const WORDS_TYPED_PER_MINUTE = 40;
/** Conversational speech, the rate audiobooks and podcasts are narrated at. */
const WORDS_SPOKEN_PER_MINUTE = 150;
/** A double-spaced manuscript page. */
const WORDS_PER_PAGE = 250;
/** Thickness of one sheet of 80gsm office paper, in millimetres. */
const PAGE_THICKNESS_MM = 0.1;
/** A typical work email, not counting the signature. */
const WORDS_PER_EMAIL = 100;

/** Published word counts for works whose size people can already picture. */
const WORKS: { words: number; one: string; many: (n: string) => string }[] = [
  {
    words: 587_287,
    one: "one full copy of War and Peace",
    many: (n) => `${n} copies of War and Peace`,
  },
  {
    words: 1_084_170,
    one: "all seven Harry Potter books, cover to cover",
    many: (n) => `all seven Harry Potter books, ${n} times over`,
  },
  {
    words: 481_103,
    one: "the whole Lord of the Rings trilogy",
    many: (n) => `${n} trips through the Lord of the Rings`,
  },
  {
    words: 884_647,
    one: "every play and sonnet Shakespeare wrote",
    many: (n) => `everything Shakespeare wrote, ${n} times`,
  },
  {
    words: 783_137,
    one: "the entire King James Bible",
    many: (n) => `${n} King James Bibles`,
  },
];

/** One decimal, but never a trailing ".0" — "3 novels" beats "3.0 novels". */
function num(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return rounded >= 100
    ? Math.round(rounded).toLocaleString()
    : String(rounded);
}

function plural(value: number, one: string, many: string): string {
  return Math.round(value * 10) / 10 === 1 ? one : many;
}

/** Shown only above `floor`, so every line that appears carries a real number. */
function above(value: number, floor: number, text: string): string | null {
  return value >= floor ? text : null;
}

/** A duration in minutes, said in whichever unit reads best at that size. */
function duration(minutes: number, suffix: string): string | null {
  const hours = minutes / 60;
  const days = hours / 24;
  const years = days / 365;
  if (years >= 1) return `${num(years)} years ${suffix}`;
  if (days >= 1) return `${num(days)} days ${suffix}`;
  return above(hours, 1, `${num(hours)} hours ${suffix}`);
}

type Comparison = (words: number) => string | null;

const COMPARISONS: Comparison[] = [
  (w) => {
    const n = w / WORDS_PER_NOVEL;
    return above(n, 0.5, `${num(n)} ${plural(n, "novel", "novels")}`);
  },
  (w) => {
    const s = w / (WORDS_PER_NOVEL * NOVELS_PER_SHELF);
    return above(
      s,
      0.5,
      `${num(s)} packed ${plural(s, "bookshelf", "bookshelves")}`,
    );
  },
  // Printed out and stacked: 0.1 mm a sheet, so the pile height is real.
  (w) => {
    const pages = w / WORDS_PER_PAGE;
    const metres = (pages * PAGE_THICKNESS_MM) / 1000;
    if (metres >= 1)
      return `a ${num(metres)}-metre stack of paper if you printed it`;
    return above(pages, 100, `${num(pages)} printed pages`);
  },
  (w) => duration(w / WORDS_SPOKEN_PER_MINUTE, "of audiobook"),
  (w) => duration(w / WORDS_READ_PER_MINUTE, "of reading without sleeping"),
  (w) => duration(w / WORDS_TYPED_PER_MINUTE, "of typing without a break"),
  (w) => {
    const days = w / WORDS_SPOKEN_PER_DAY;
    const years = days / 365;
    if (years >= 1)
      return `${num(years)} years of everything you'd say out loud`;
    return above(days, 1, `${num(days)} days of everything you'd say out loud`);
  },
  (w) => {
    const emails = w / WORDS_PER_EMAIL;
    return above(emails, 50, `${num(emails)} emails' worth of writing`);
  },
  // One line per famous work, phrased for its own size: below two copies,
  // "1.3 copies of War and Peace" reads worse than naming the book outright.
  ...WORKS.map<Comparison>(({ words, one, many }) => (w) => {
    const n = w / words;
    if (n >= 2) return many(num(n));
    return above(n, 0.9, one);
  }),
];

/** Every comparison worth saying about a token total, in a stable order. */
export function tokenComparisons(tokens: number): string[] {
  if (tokens <= 0) return [];
  const words = tokens * WORDS_PER_TOKEN;
  return COMPARISONS.map((say) => say(words)).filter(
    (line): line is string => line !== null,
  );
}
