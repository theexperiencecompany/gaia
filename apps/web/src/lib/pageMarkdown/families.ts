/**
 * Markdown renderers for the data-driven marketing pages, one per URL family.
 *
 * Each reads the same data getter and English messages its HTML page renders,
 * so the markdown variant cannot drift from the page. English only: the
 * markdown variant describes the canonical (default-locale) page.
 */

import { createTranslator } from "next-intl";

import {
  type AlternativeData,
  getAllAlternativeSlugs,
  getAlternative,
} from "@/features/alternatives/data/alternativesData";
import {
  type ComparisonData,
  getAllComparisonSlugs,
  getComparison,
} from "@/features/comparisons/data/comparisonsData";
import {
  type GlossaryTerm,
  getAllGlossaryTermSlugs,
  getGlossaryTerm,
} from "@/features/glossary/data/glossaryData";
import {
  getAllComboSlugs,
  getCombo,
  type IntegrationCombo,
} from "@/features/integrations/data/combosData";
import { defaultLocale } from "@/i18n/config";
import { type BlogContentPost, getAllBlogSlugs, getBlogPost } from "@/lib/blog";
import messages from "@/messages/en.json";

import {
  bulletList,
  document,
  faqSection,
  numberedList,
  oneLine,
  table,
} from "./markdown";

const t = createTranslator({ locale: defaultLocale, messages });

interface MarkdownFamily<T> {
  /** The live page set; consolidated victims are absent from it. */
  slugs: () => Promise<string[]>;
  load: (slug: string) => Promise<T | undefined>;
  render: (data: T) => string;
}

/** Markdown for one slug of a family, or undefined when the slug is not a live page. */
type FamilyRenderer = (slug: string) => Promise<string | undefined>;

function markdownFamily<T>(family: MarkdownFamily<T>): FamilyRenderer {
  return async (slug) => {
    if (!(await family.slugs()).includes(slug)) return undefined;
    const data = await family.load(slug);
    if (!data) {
      throw new Error(`Listed slug has no data file: ${slug}`);
    }
    return family.render(data);
  };
}

const compare = markdownFamily<ComparisonData>({
  slugs: getAllComparisonSlugs,
  load: getComparison,
  render: (data) =>
    document([
      `# ${t("comparisons.gaia_vs", { name: data.name })}`,
      data.description,
      data.intro,
      `## ${t("comparisons.feature_comparison")}`,
      table(
        [
          t("comparisons.feature_column"),
          t("comparisons.gaia_column"),
          data.name,
        ],
        data.rows.map((row) => [row.feature, row.gaia, row.competitor]),
      ),
      `## ${t("comparisons.why_choose_gaia")}`,
      bulletList(data.gaiaAdvantages),
      `## ${t("comparisons.where_excels", { name: data.name })}`,
      bulletList(data.competitorAdvantages),
      `## ${t("comparisons.the_verdict")}`,
      data.verdict,
      faqSection(t("common.faq"), data.faqs),
    ]),
});

const alternativeTo = markdownFamily<AlternativeData>({
  slugs: getAllAlternativeSlugs,
  load: getAlternative,
  render: (data) =>
    document([
      `# ${t("alternatives.best_alternative_year", { name: data.name })}`,
      data.tagline,
      data.whyPeopleLook,
      `## ${t("alternatives.why_people_look", { name: data.name })}`,
      bulletList(data.painPoints),
      `## ${t("alternatives.how_well_replace", { name: data.name })}`,
      `${t("alternatives.honest_fit_score")}: ${data.gaiaFitScore}/5`,
      `## ${t("alternatives.what_gaia_replaces", { name: data.name })}`,
      bulletList(data.gaiaReplaces),
      ...(data.comparisonRows && data.comparisonRows.length > 0
        ? [
            `## ${t("alternatives.feature_comparison", { name: data.name })}`,
            table(
              [
                t("alternatives.feature_column"),
                t("alternatives.gaia_column"),
                data.name,
              ],
              data.comparisonRows.map((row) => [
                row.feature,
                row.gaia,
                row.competitor,
              ]),
            ),
          ]
        : []),
      `## ${t("alternatives.where_gaia_further")}`,
      bulletList(data.gaiaAdvantages),
      `## ${t("alternatives.how_to_migrate", { name: data.name })}`,
      numberedList(data.migrationSteps),
      faqSection(t("common.faq"), data.faqs),
    ]),
});

const learn = markdownFamily<GlossaryTerm>({
  slugs: getAllGlossaryTermSlugs,
  load: getGlossaryTerm,
  render: (data) =>
    document([
      `# ${data.term}`,
      data.definition,
      `## ${t("glossary.understanding")} ${data.term}`,
      data.extendedDescription,
      `## ${t("glossary.how_gaia_uses")} ${data.term}`,
      data.howGaiaUsesIt,
      faqSection(t("common.faq"), data.faqs),
    ]),
});

const automate = markdownFamily<IntegrationCombo>({
  slugs: getAllComboSlugs,
  load: getCombo,
  render: (data) => {
    const tools = { toolA: data.toolA, toolB: data.toolB };
    return document([
      `# ${t("automate.automate_with_gaia", tools)}`,
      data.tagline,
      data.intro,
      `## ${data.useCases.length} ${t("automate.things_you_can_automate")}`,
      t("automate.everything_gaia_can_do", tools),
      ...data.useCases.map(
        (useCase) => `### ${oneLine(useCase.title)}\n\n${useCase.description}`,
      ),
      `## ${t("automate.how_to_set_it_up")}`,
      t("automate.connect_in_steps", tools),
      ...data.howItWorks.map(
        (step, index) =>
          `### ${index + 1}. ${oneLine(step.step)}\n\n${step.description}`,
      ),
      faqSection(t("common.faq"), data.faqs),
    ]);
  },
});

const blog = markdownFamily<BlogContentPost>({
  slugs: getAllBlogSlugs,
  load: async (slug) => (await getBlogPost(slug)) ?? undefined,
  render: (post) =>
    document([
      `# ${post.title}`,
      [
        `By ${post.authors.map((author) => author.name).join(", ")}`,
        `Published ${post.date}`,
        ...(post.updated ? [`Updated ${post.updated}`] : []),
        post.category,
      ].join(" · "),
      post.content,
    ]),
});

/** URL family (the first path segment) to its renderer: the only pages with a markdown variant besides the homepage. */
const FAMILIES: Readonly<Record<string, FamilyRenderer>> = {
  compare,
  "alternative-to": alternativeTo,
  learn,
  automate,
  blog,
};

/** The URL families that have markdown variants. */
export const MARKDOWN_FAMILY_NAMES = Object.keys(FAMILIES);

/** Markdown for `/<family>/<slug>`, or undefined when that page has no variant. */
export async function renderFamilyPage(
  familyName: string,
  slug: string,
): Promise<string | undefined> {
  const render = Object.hasOwn(FAMILIES, familyName)
    ? FAMILIES[familyName]
    : undefined;
  return render ? render(slug) : undefined;
}
