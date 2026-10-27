/**
 * A wizard step for one feature, through the same picker Settings uses: what
 * the feature runs on now, one provider select, then only that provider's
 * fields. The AI-models step needs one saved provider to continue; web search
 * already works on its free built-in engine, so its step is skippable.
 */

"use client";

import type { ProviderFeature } from "@shared/api/generated";
import * as m from "motion/react-m";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { FeatureProviderPicker } from "@/features/settings/components/providers/FeatureProviderPicker";
import { resolveFeatureGroup } from "@/features/settings/components/providers/providerRows";

interface FeatureStepProps {
  feature: ProviderFeature;
  status: SetupStatus;
  catalog: ProviderCatalog;
}

export function FeatureStep({ feature, status, catalog }: FeatureStepProps) {
  return (
    <m.div className="w-full rounded-2xl bg-zinc-900 p-4" {...MOTION_FADE_UP}>
      <FeatureProviderPicker
        group={resolveFeatureGroup(feature, catalog, status)}
        catalog={catalog}
        status={status}
      />
    </m.div>
  );
}
