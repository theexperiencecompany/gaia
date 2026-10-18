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
  "セルフホス(?:ト|ティング)|自己ホスト",
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

/** The licence's name, which is not itself a non-commercial qualifier. */
const LICENCE_NAME = /PolyForm Noncommercial/gi;

/** An organisation running GAIA, in any locale. */
const ORGANISATION = anyOf([
  String.raw`organi[sz]ations?|business(?:es)?|\bfirms?\b|compan(?:y|ies)|enterprises?\b|\bteams?\b|employers?|agenc(?:y|ies)|startups?|corporate`,
  "Organisation|Unternehmen|Firm(?:a|en)|Team|Kanzlei|Konzern",
  "entreprise|société|cabinet|équipe",
  "organizaci|empresa|compañía|despacho|equipo|bufete",
  "organiza[çc]|companhia|escritório|equipe",
  "組織|企業|会社|事務所|チーム|法人",
  "조직|기업|회사|팀|법인|사무소",
]);

/** The licence an organisation self-hosts GAIA under. */
const ENTERPRISE_LICENCE = anyOf([
  "enterprise licen[cs]e",
  "Enterprise-Lizenz|Unternehmenslizenz",
  "licence (?:Enterprise|entreprise)",
  "licencia (?:Enterprise|empresarial)|licença (?:Enterprise|empresarial)",
  "エンタープライズライセンス|企業向けライセンス",
  "엔터프라이즈 라이선스|기업용 라이선스",
]);

/** Organisations the noncommercial licence itself covers: schools, charities, public bodies. */
const NONCOMMERCIAL_ORGANISATION = anyOf([
  String.raw`non-?profit|charit|school|universit|educational|government|public (?:research|health|safety|sector)`,
  "gemeinnützig|Schule|Hochschule|Universität|Bildungseinrichtung|Behörde|öffentliche",
  "but non lucratif|associations?|écoles?|universit|établissements? d'enseignement|administrations? publique|organismes? public",
  "sin fines de lucro|escuelas?|universidad|centros? educativos?|instituci[oó]n(?:es)? (?:educativa|pública)|gobierno|sector público",
  "sem fins lucrativos|escolas?|universidade|instituiç(?:ão|ões) de ensino|governo|setor público",
  "非営利|学校|大学|教育機関|政府|公的機関|公共",
  "비영리|학교|대학|교육 기관|정부|공공",
]);

/** A for-profit organisation, the only kind the enterprise licence is for. */
const FOR_PROFIT = anyOf([
  String.raw`for-profit|business|compan(?:y|ies)|\bfirms?\b|commercial|startups?|agenc(?:y|ies)|corporat|employers?`,
  "gewinnorientiert|Unternehmen|Firm(?:a|en)|Kanzlei|kommerziell|gewerblich",
  "à but lucratif|entreprises?|sociétés?|cabinets?|commercia",
  "con fines de lucro|empresas?|bufetes?|despachos?|comercial",
  "com fins lucrativos|empresas?|escritórios?|comercia",
  "営利|企業|会社|法人|事務所|商用",
  "영리|기업|회사|법인|사무소|상업",
]);

/** Hosted GAIA priced as if one plan covered a whole team: it is one subscription per account. */
const FLAT_TEAM_PRICE = anyOf([
  String.raw`regardless of (?:the )?(?:team size|seat|headcount|(?:the )?number of (?:users|seats|people)|how many (?:users|seats|people))|not per seat|no per-seat|without per-seat|flat (?:rate )?(?:\(not per seat\)|for (?:the whole|your) team)`,
  "unabhängig von (?:der )?(?:Teamgröße|Nutzerzahl|Anzahl der (?:Nutzer|Benutzer|Sitze|Personen)|Sitzplatz)|ohne (?:Sitzplatz|Pro-Sitz|nutzerbasierte)|keine (?:Sitzplatz|Pro-Sitz|nutzerbasierten|Benutzersitz)",
  "quel que soit (?:le nombre|la taille)|indépendamment (?:du nombre|de la taille)|sans (?:frais|tarif|coût)s? par (?:siège|utilisateur)|pas de (?:frais|tarif|coût)s? par (?:siège|utilisateur)",
  "independientemente del? (?:tamaño|número)|sin importar (?:el tamaño|el número|cuántos)|sin (?:costo|coste|precio|cargo)s? por (?:asiento|usuario)",
  "independente(?:mente)? d[oa] (?:tamanho|número)|sem (?:custo|cobrança|preço)s? por (?:assento|usuário)",
  "人数に(?:関係なく|かかわらず|関わらず)|ユーザー数に(?:関係なく|かかわらず)|席数に(?:関係なく|かかわらず)|シート単位の(?:課金|料金)(?:は)?(?:なし|ありません)",
  "(?:좌석|인원|사용자|팀) ?(?:수|규모)(?:에|와|과) (?:관계없이|상관없이)|좌석당 (?:비용|요금)(?:이|은)? (?:없|없이)",
  String.raw`\bflat\b[^.;]{0,60}\b(?:teams?|seats?|users|headcount)\b|(?:cheaper|cost-effective|less expensive|more affordable|saves? money)[^.;]{0,60}\bteams?\b`,
  "pauschal[^.;]{0,60}(?:Team|Nutzer|Sitz)|(?:günstiger|kostengünstiger|preiswerter)[^.;]{0,60}Team",
  "(?:fixe|forfaitaire)[^.;]{0,60}(?:équipe|utilisateur|siège)|sans restriction par siège|(?:moins cher|plus économique|plus rentable)[^.;]{0,60}équipe",
  "(?:fijo|tarifa plana)[^.;]{0,60}(?:equipo|usuario|asiento)|sin importar la cantidad|(?:más barato|más económico|más rentable)[^.;]{0,60}equipo",
  "(?:fixo|preço único)[^.;]{0,60}(?:equipe|usuário|assento)|(?:mais barato|mais econômico|mais em conta|mais vantajoso)[^.;]{0,60}equipe",
  "定額[^。]{0,40}(?:チーム|ユーザー|人数|席)|チーム[^。]{0,30}(?:安く|割安|お得|コスト効率|経済的)|(?:安く|割安|お得|コスト効率|経済的)[^。]{0,30}チーム",
  "정액[^.]{0,40}(?:팀|사용자|인원|좌석)|팀[^.]{0,30}(?:저렴|경제적|비용 효율)|(?:저렴|경제적|비용 효율)[^.]{0,30}팀",
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
  persona: boolean;
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
  unownedIsGaia = GAIA_VOICE_FIELDS.has(String(context.field)),
): boolean {
  const field = typeof context.field === "string" ? context.field : "";
  if (GAIA_FIELDS.has(field)) return true;
  const end = match.index + match[0].length;
  if (ownedAfter(clause, end, context.competitors)) return false;
  const owner = ownerBefore(clause, end, context.competitors);
  if (owner === "gaia") return true;
  if (owner === "competitor")
    return /\bboth\b|\bbeide|\bambos|\btous les deux/i.test(clause);
  return unownedIsGaia && /gaia/i.test(context.text);
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
    aboutGaia(clause, selfHosting, context, /gaia/i.test(clause))
  );
}

/** Self-hosting pitched to a business or a working professional with no enterprise licence named. */
function organisationSelfHostingWithoutLicence(
  clause: string,
  context: Context,
): boolean {
  const selfHosting = SELF_HOSTING.exec(clause);
  if (
    selfHosting === null ||
    NONCOMMERCIAL.test(clause.replaceAll(LICENCE_NAME, "")) ||
    NONCOMMERCIAL_ORGANISATION.test(clause) ||
    ENTERPRISE_LICENCE.test(context.text)
  )
    return false;
  return (
    (context.persona || ORGANISATION.test(clause)) &&
    aboutGaia(clause, selfHosting, context, /gaia/i.test(clause))
  );
}

/** The enterprise licence asked of every organisation, though schools and charities need none. */
function enterpriseLicenceForEveryOrganisation(clause: string): boolean {
  return ENTERPRISE_LICENCE.test(clause) && !FOR_PROFIT.test(clause);
}

function flatTeamPrice(clause: string, context: Context): boolean {
  const claim = FLAT_TEAM_PRICE.exec(clause);
  if (claim === null) return false;
  if (GAIA_FIELDS.has(String(context.field))) return true;
  const owner = ownerBefore(clause, claim.index, context.competitors);
  return owner === "gaia" || (owner === null && /gaia/i.test(clause));
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
      persona: relative.split(path.sep).includes("personas"),
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

  it("offers organisations self-hosting only under an enterprise licence", () => {
    const claims = MARKETING_FILES.flatMap((file) =>
      findings(file, readJson(file), organisationSelfHostingWithoutLicence),
    );
    expect(claims).toEqual([]);
  });

  it("asks only for-profit organisations for an enterprise licence", () => {
    const claims = MARKETING_FILES.flatMap((file) =>
      findings(file, readJson(file), enterpriseLicenceForEveryOrganisation),
    );
    expect(claims).toEqual([]);
  });

  it("prices hosted GAIA per account, never flat for a team", () => {
    const claims = MARKETING_FILES.flatMap((file) =>
      findings(file, readJson(file), flatTeamPrice),
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

  it("flags a business self-hosting pitch that names no enterprise license", () => {
    const notion = path.join(DATA_DIR, "comparisons", "notion.json");
    const count = (text: string) =>
      findings(notion, { answer: text }, organisationSelfHostingWithoutLicence)
        .length;

    expect(count("Law firms can self-host GAIA for data sovereignty.")).toBe(1);
    expect(
      count("GAIA (PolyForm Noncommercial) is self-hostable for your team."),
    ).toBe(1);
    expect(
      count(
        "Law firms can self-host GAIA under an enterprise license for data sovereignty.",
      ),
    ).toBe(0);
    expect(count("Self-hosting is free for non-commercial use.")).toBe(0);
    expect(count("Schools can self-host GAIA free as non-profits.")).toBe(0);
  });

  it("flags an enterprise licence asked of every organisation and a flat team price", () => {
    const notion = path.join(DATA_DIR, "comparisons", "notion.json");
    const count = (
      text: string,
      rule: (clause: string, context: Context) => boolean,
    ) => findings(notion, { answer: text }, rule).length;

    expect(
      count(
        "Organizations can self-host GAIA under an enterprise license.",
        enterpriseLicenceForEveryOrganisation,
      ),
    ).toBe(1);
    expect(
      count(
        "For-profit organizations need an enterprise license.",
        enterpriseLicenceForEveryOrganisation,
      ),
    ).toBe(0);
    expect(
      count("GAIA Pro is $30/month regardless of team size.", flatTeamPrice),
    ).toBe(1);
    expect(
      count(
        "GAIA's flat pricing is dramatically cheaper for teams.",
        flatTeamPrice,
      ),
    ).toBe(1);
    expect(
      count(
        "Notion charges per seat; GAIA Pro is $30/month per person.",
        flatTeamPrice,
      ),
    ).toBe(0);
  });
});
