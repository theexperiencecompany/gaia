/**
 * Hosted GAIA is paid-only: no marketing data or message string may claim a
 * GAIA free tier, free plan or free start, in any locale. Within a clause a
 * free-tier phrase belongs to the product named nearest before it, so
 * "Notion's free plan" passes and "GAIA has a free plan" fails. Self-hosting
 * is free only for non-commercial use, so a free self-hosting claim says so.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const DATA_DIR = path.join(process.cwd(), "public", "data");
const MESSAGES_DIR = path.join(process.cwd(), "src", "messages");

function anyOf(patterns: string[]): RegExp {
  return new RegExp(patterns.join("|"), "i");
}

/** A free tier, plan or version, whoever owns it. */
const FREE_TIER = anyOf([
  String.raw`\bfree(?: hosted)?[- ](?:tier|plan|version|account|edition|level|option)s?\b`,
  String.raw`\bfreemium\b`,
  String.raw`\bfree forever\b`,
  String.raw`kostenlose[nrs]?,?\s(?:gehostete\s)?(?:Stufe|Version|Basisversion|Plan|Tarif|Einstieg|Konto|Variante)`,
  String.raw`\bGratis-?(?:Tarif|Plan|Version|Stufe)`,
  "(?:niveau|version|offre|formule|forfait|palier|compte|plan)s? gratuite?s?",
  "(?:plan|nivel|versión|capa|cuenta|opción|plano|versão|camada|conta)(?:es|s)? (?:gratuit[oa]s?|grátis|gratis)",
  "無料(?:プラン|ティア|版|枠|アカウント|あり|があり)",
  String.raw`무료\s?(?:티어|플랜|요금제|등급|버전|계정)|프리\s?티어|무료가\s(?:있|딸)`,
]);

/** GAIA itself called free, or a free start offered. */
const FREE_GAIA = anyOf([
  String.raw`\b(?:is|are) GAIA (?:\S+ )?free\b`,
  String.raw`\bGAIA (?:is|stays|remains) (?:a |the |completely |totally |fully )?free\b`,
  String.raw`\bGAIA\b[^.]{0,40}\bfree,? (?:\S+ )?alternative`,
  String.raw`\b(?:start|sign up|get started|try)(?: for)?(?: GAIA| it)?(?: for)? free\b`,
  String.raw`\bfree to (?:start|use|try|get started|sign up)\b`,
  String.raw`\bfree tier (?:included|available)\b`,
  String.raw`\bno credit card\b`,
  String.raw`\bist GAIA (?:\S+ )?kostenlos|\bGAIA ist (?:die |eine |komplett |völlig |vollständig )?kostenlos`,
  "kostenlos (?:anmelden|starten|testen|loslegen|nutzbar)|ohne Kreditkarte",
  String.raw`GAIA est(?:-il)? (?:\S+ )?gratuit|inscrivez-vous grat|commencez gratuitement|sans carte (?:bancaire|de crédit)`,
  String.raw`GAIA es (?:\S+ )?(?:gratuit|gratis)|(?:regístrate|empieza|comienza) gratis|sin tarjeta de crédito`,
  String.raw`o GAIA é (?:\S+ )?(?:gratuit|grátis)|(?:cadastre-se|comece) (?:grátis|gratuitamente)|sem cartão de crédito`,
  "GAIAは(?:完全に)?無料|無料で(?:始め|使え|利用でき)|クレジットカード(?:は)?不要",
  String.raw`GAIA(?:는|은) (?:완전히 )?무료|무료로 (?:시작|사용|이용)|신용카드\s?(?:불필요|필요 없|없이)`,
]);

/** Free in any locale, for the self-hosting check. */
const FREE_WORD = anyOf([
  String.raw`\bfree\b|\bfor free\b`,
  String.raw`kostenlos|kostenfrei|\bgratuit|\bgratis|grátis|sans frais|sin cost[eo]|sem custo`,
  "無料|무료",
]);

/** A clause about self-hosting GAIA. */
const SELF_HOSTING = anyOf([
  "self[- ]?host",
  String.raw`selbst\s?(?:-\s?)?(?:gehost|hostbar|host)|Selbsthost`,
  "auto-?héberg|autoaloj|autohosped|auto-?hosped|hospedar o GAIA|instalação própria",
  "セルフホスト|自己ホスト",
  String.raw`자체\s?호스팅|셀프\s?호스팅|직접 (?:서버|호스팅)`,
]);

/** The licence condition that makes self-hosting free. */
const NONCOMMERCIAL = anyOf([
  "non-?commercial|personal use",
  "nicht-?kommerziell|private Nutzung",
  "non commercia|usage personnel",
  "no comercial|uso personal|não comercial|uso pessoal",
  "非商用|非営利|個人利用",
  "비상업|개인 용도",
]);

/** Fields that describe GAIA's side of a comparison, where any free tier is GAIA's. */
const GAIA_FIELDS = new Set(["gaia", "gaiaAdvantages"]);

/** Fields that describe the competitor, where a free plan is theirs. */
const COMPETITOR_FIELDS = new Set(["competitor", "competitorAdvantages"]);

/** Fields where a free tier no product claims is GAIA's: its own page copy. */
const GAIA_VOICE_FIELDS = new Set(["metaTitle", "metaDescription"]);

/** "No free tier", "keine kostenlose Stufe", "pas de niveau gratuit": a free tier denied. */
const NEGATED_BEFORE =
  /(?:(?:\bno|\bnot? an?|keine[nm]?|\bkein|\bohne|\bsans|\bni|\bsin|\bsem|não tem|nenhum|pas de)\s+(?:\S+\s+)?|pas d['’])$/i;
const NEGATED_AFTER = /^\S*\s?(?:が?ありません|はありません|なし|は?없)/;

/** A clause ends at punctuation followed by a space, or at CJK punctuation; "Cal.com" stays whole. */
const CLAUSE = /(?<=[.!?;])\s+|(?<=[。！？；])/;

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

interface Finding {
  file: string;
  path: string;
  clause: string;
}

function* strings(
  node: Json,
  at: (string | number)[] = [],
): Generator<[(string | number)[], string]> {
  if (typeof node === "string") yield [at, node];
  else if (Array.isArray(node))
    for (const [i, child] of node.entries()) yield* strings(child, [...at, i]);
  else if (node && typeof node === "object")
    for (const [key, child] of Object.entries(node))
      yield* strings(child, [...at, key]);
}

function readJson(file: string): Json {
  return JSON.parse(readFileSync(file, "utf8"));
}

function jsonFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .map((entry) => path.join(entry.parentPath, entry.name));
}

const competitorsByFile = new Map<string, string[]>();

/** The products an entry compares GAIA with, read from its base file. */
function competitorNames(file: string, at: (string | number)[]): string[] {
  if (!file.startsWith(DATA_DIR)) return [];
  const relative = path.relative(DATA_DIR, file).split(path.sep);
  const [feature, slug] =
    relative[0] === "i18n"
      ? [relative[1], String(at[0])]
      : [relative[0], relative[1].replace(/\.json$/, "")];
  const baseFile = path.join(DATA_DIR, feature, `${slug}.json`);
  const cached = competitorsByFile.get(baseFile);
  if (cached) return cached;
  const base = existsSync(baseFile) ? readJson(baseFile) : null;
  const names =
    base && typeof base === "object" && !Array.isArray(base)
      ? [base.name, base.toolA, base.toolB]
          .filter((name): name is string => typeof name === "string")
          .filter((name) => !/^GAIA\b/i.test(name))
          .flatMap((name) => [
            name,
            ...name.split(/[\s.]/).filter((word) => word.length >= 4),
          ])
      : [];
  competitorsByFile.set(baseFile, names);
  return names;
}

/** Whether the product named last before `index` is GAIA, a competitor, or nothing. */
function ownerBefore(
  clause: string,
  index: number,
  competitors: string[],
): "gaia" | "competitor" | null {
  const before = clause.slice(0, index).toLowerCase();
  const gaiaAt = before.lastIndexOf("gaia");
  const competitorAt = Math.max(
    -1,
    ...competitors.map((name) => before.lastIndexOf(name.toLowerCase())),
  );
  if (gaiaAt < 0 && competitorAt < 0) return null;
  return gaiaAt > competitorAt ? "gaia" : "competitor";
}

interface Context {
  text: string;
  field: string | number | undefined;
  competitors: string[];
}

/** Whether a competitor owns the phrase from after it: "l'offre gratuite de Notion". */
function ownedAfter(
  clause: string,
  end: number,
  competitors: string[],
): boolean {
  const after = clause
    .slice(end)
    .toLowerCase()
    .replace(/^\s*(?:de|d['’]|du|von|der|des|do|da|of)\s*/, "");
  return competitors.some((name) => after.startsWith(name.toLowerCase()));
}

/** Whether the phrase `match` speaks about GAIA rather than another product. */
function aboutGaia(
  clause: string,
  match: RegExpExecArray,
  context: Context,
): boolean {
  const field = typeof context.field === "string" ? context.field : "";
  if (GAIA_FIELDS.has(field)) return true;
  const end = match.index + match[0].length;
  if (ownedAfter(clause, end, context.competitors)) return false;
  const owner = ownerBefore(clause, end, context.competitors);
  if (owner === "gaia") return true;
  if (owner === "competitor")
    return /\bboth\b|\bbeide|\bambos|\btous les deux/i.test(clause);
  return GAIA_VOICE_FIELDS.has(field) && /gaia/i.test(context.text);
}

function negated(clause: string, match: RegExpExecArray): boolean {
  const end = match.index + match[0].length;
  return (
    NEGATED_BEFORE.test(clause.slice(0, match.index)) ||
    NEGATED_AFTER.test(clause.slice(end))
  );
}

function claimsGaiaFreeTier(clause: string, context: Context): boolean {
  const freeGaia = SELF_HOSTING.test(clause) ? null : FREE_GAIA.exec(clause);
  const claim = freeGaia ?? FREE_TIER.exec(clause);
  return (
    claim !== null &&
    !negated(clause, claim) &&
    aboutGaia(clause, claim, context)
  );
}

function freeSelfHostingWithoutLicence(
  clause: string,
  context: Context,
): boolean {
  const selfHosting = SELF_HOSTING.exec(clause);
  return (
    selfHosting !== null &&
    FREE_WORD.test(clause) &&
    !NONCOMMERCIAL.test(clause) &&
    aboutGaia(clause, selfHosting, context)
  );
}

function findings(
  file: string,
  data: Json,
  rule: (clause: string, context: Context) => boolean,
): Finding[] {
  const relative = path.relative(process.cwd(), file);
  return [...strings(data)].flatMap(([at, text]) => {
    if (at.some((key) => COMPETITOR_FIELDS.has(String(key)))) return [];
    const context = {
      text,
      field: at.at(-1),
      competitors: competitorNames(file, at),
    };
    return text
      .split(CLAUSE)
      .filter((clause) => rule(clause, context))
      .map((clause) => ({ file: relative, path: at.join("."), clause }));
  });
}

const MARKETING_FILES = [...jsonFiles(DATA_DIR), ...jsonFiles(MESSAGES_DIR)];

describe("paid-only marketing copy", () => {
  it("claims no GAIA free tier in any marketing data or message string", () => {
    const claims = MARKETING_FILES.flatMap((file) =>
      findings(file, readJson(file), claimsGaiaFreeTier),
    );
    expect(claims).toEqual([]);
  });

  it("calls self-hosting free only for non-commercial use", () => {
    const claims = MARKETING_FILES.flatMap((file) =>
      findings(file, readJson(file), freeSelfHostingWithoutLicence),
    );
    expect(claims).toEqual([]);
  });

  it("flags a GAIA free tier and keeps a competitor's", () => {
    const notion = path.join(DATA_DIR, "comparisons", "notion.json");
    const count = (text: string, field = "answer") =>
      findings(notion, { [field]: text }, claimsGaiaFreeTier).length;

    expect(count("GAIA has a free tier.")).toBe(1);
    expect(count("Free tier available; Pro from $9/month", "gaia")).toBe(1);
    expect(count("Is GAIA free like Notion's free plan?")).toBe(1);
    expect(count("GAIAには無料プランがあります。")).toBe(1);
    expect(count("GAIA hat keine kostenlose Stufe.")).toBe(0);
    expect(
      count("Comment GAIA se compare-t-il à l'offre gratuite de Notion ?"),
    ).toBe(0);
    expect(count("Notion's free plan covers pages, and GAIA is paid.")).toBe(0);
    expect(count("Self-hosted GAIA is free for non-commercial use.")).toBe(0);
  });
});
