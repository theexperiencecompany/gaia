import Link from "next/link";

import {
  CATEGORY_ORDER,
  COMPARISON_CATEGORIES,
} from "@/features/comparisons/data/categories";

interface LinkedGuide {
  readonly slug: string;
  readonly name: string;
  readonly tagline?: string;
}

interface LinkedGuideGroup {
  readonly category: string;
  readonly guides: readonly LinkedGuide[];
}

const CATEGORY_RANK = new Map<string, number>(
  CATEGORY_ORDER.map((category, index) => [category, index]),
);

/** Group the flattened, pre-sorted guides by the categories the compare hub uses, keeping their order within each group. */
function groupGuides(guides: readonly LinkedGuide[]): LinkedGuideGroup[] {
  const grouped = new Map<string, LinkedGuide[]>();

  for (const guide of guides) {
    const category = COMPARISON_CATEGORIES[guide.slug] ?? "Other";
    const existing = grouped.get(category);
    if (existing) {
      existing.push(guide);
    } else {
      grouped.set(category, [guide]);
    }
  }

  return [...grouped.entries()]
    .sort(
      ([a], [b]) =>
        (CATEGORY_RANK.get(a) ?? CATEGORY_ORDER.length) -
        (CATEGORY_RANK.get(b) ?? CATEGORY_ORDER.length),
    )
    .map(([category, groupedGuides]) => ({
      category,
      guides: groupedGuides,
    }));
}

function GuideGroups({
  guides,
  href,
  text,
  ariaLabel,
}: {
  readonly guides: readonly LinkedGuide[];
  readonly href: (slug: string) => string;
  readonly text: (guide: LinkedGuide) => string;
  readonly ariaLabel: (guide: LinkedGuide) => string;
}) {
  return (
    <div className="columns-2 gap-6 text-sm leading-loose text-zinc-400 sm:columns-3">
      {groupGuides(guides).map((group) => (
        <ul key={group.category} className="contents">
          {group.guides.map((guide) => (
            <li key={guide.slug} className="break-inside-avoid">
              <Link
                href={href(guide.slug)}
                aria-label={ariaLabel(guide)}
                className="hover:text-zinc-200 hover:underline hover:underline-offset-2"
              >
                {text(guide)}
              </Link>
            </li>
          ))}
        </ul>
      ))}
    </div>
  );
}

export function BestHubComparisonLinks({
  title,
  comparisons,
}: {
  readonly title: string;
  readonly comparisons: readonly LinkedGuide[];
}) {
  return (
    <section className="mb-16">
      <h2 className="mb-4 text-3xl font-semibold text-white">{title}</h2>
      <p className="mb-6 leading-relaxed text-zinc-400">
        We publish a full head-to-head for each tool below. Start from the{" "}
        <Link
          href="/compare"
          className="underline underline-offset-2 hover:text-zinc-200"
        >
          comparisons hub
        </Link>{" "}
        or jump straight in:
      </p>
      <GuideGroups
        guides={comparisons}
        href={(slug) => `/compare/${slug}`}
        text={(comparison) => `GAIA vs ${comparison.name}`}
        ariaLabel={(comparison) =>
          comparison.tagline
            ? `GAIA vs ${comparison.name}: ${comparison.tagline}`
            : `GAIA vs ${comparison.name} comparison`
        }
      />
    </section>
  );
}

export function BestHubAlternativeLinks({
  title,
  alternatives,
}: {
  readonly title: string;
  readonly alternatives: readonly LinkedGuide[];
}) {
  return (
    <section className="mb-16">
      <h2 className="mb-4 text-3xl font-semibold text-white">{title}</h2>
      <p className="mb-6 leading-relaxed text-zinc-400">
        Migration-focused guides with fit scores and switch steps. Browse the{" "}
        <Link
          href="/alternative-to"
          className="underline underline-offset-2 hover:text-zinc-200"
        >
          alternatives hub
        </Link>{" "}
        or jump straight in:
      </p>
      <GuideGroups
        guides={alternatives}
        href={(slug) => `/alternative-to/${slug}`}
        text={(alternative) => `${alternative.name} alternatives`}
        ariaLabel={(alternative) => `${alternative.name} alternatives guide`}
      />
    </section>
  );
}
