/**
 * Guide pages data — the top-level `/{slug}` assistant guides.
 *
 * Per-slug entries live in `apps/web/public/data/guides/{slug}.json`, each
 * served by its own static route that names its slug.
 */

import { getFeatureEntry } from "@/lib/feature-data";
import type { GuideData } from "./guidesData.types";

const FEATURE = "guides";

/** Load a guide; a static route whose data file is missing is a build error, not a 404. */
export async function getGuide(slug: string): Promise<GuideData> {
  const guide = await getFeatureEntry<GuideData>(FEATURE, slug);
  if (!guide) {
    throw new Error(`Missing guide data: public/data/${FEATURE}/${slug}.json`);
  }
  return guide;
}
