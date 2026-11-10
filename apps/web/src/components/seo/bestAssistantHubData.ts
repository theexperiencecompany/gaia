import {
  getAllAlternatives,
  getAlternative,
} from "@/features/alternatives/data/alternativesData";
import {
  type ComparisonData,
  getAllComparisons,
  getComparison,
} from "@/features/comparisons/data/comparisonsData";
import { canonicalHref, isRedirectedPath } from "@/lib/canonicalLinks";
import type { BestHubConfig } from "./bestAssistantHubConfig";

export interface RankedPick {
  readonly data: ComparisonData;
  readonly compareHref: string;
  readonly alternativeHref: string | undefined;
}

async function loadRankedPick(slug: string): Promise<RankedPick | undefined> {
  const data = await getComparison(slug);
  if (!data) return undefined;
  const alternative = await getAlternative(slug);
  const compareHref = canonicalHref(`/compare/${slug}`);
  const alternativePath = `/alternative-to/${slug}`;
  return {
    data,
    compareHref,
    alternativeHref:
      alternative !== undefined &&
      !isRedirectedPath(alternativePath) &&
      alternativePath !== compareHref
        ? alternativePath
        : undefined,
  };
}

function byName<T extends { readonly name: string }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => a.name.localeCompare(b.name));
}

export async function loadBestHubData(config: BestHubConfig) {
  const [picks, allComparisons, allAlternatives] = await Promise.all([
    Promise.all(config.rankedSlugs.map(loadRankedPick)),
    getAllComparisons(),
    getAllAlternatives(),
  ]);

  const ranked: RankedPick[] = [];
  const missingSlugs: string[] = [];
  picks.forEach((pick, index) => {
    const slug = config.rankedSlugs[index];
    if (pick === undefined) {
      missingSlugs.push(slug);
    } else {
      ranked.push(pick);
    }
  });
  if (missingSlugs.length > 0) {
    throw new Error(
      `${config.pagePath}: missing comparison data for slugs: ${missingSlugs.join(", ")}`,
    );
  }

  const poolSlugs = new Set(config.rankedSlugs);
  const inPool = <T extends { readonly slug: string }>(item: T) =>
    poolSlugs.has(item.slug);

  return {
    ranked,
    listedComparisons: byName(allComparisons.filter(inPool)),
    listedAlternatives: byName(allAlternatives.filter(inPool)),
  };
}
