/**
 * Wizard step 2 — web search already works on its free built-in engine; the
 * shared provider picker offers the optional upgrades, one provider at a time.
 * Entirely skippable.
 */

"use client";

import * as m from "motion/react-m";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { FeatureProviderPicker } from "@/features/settings/components/providers/FeatureProviderPicker";
import { resolveFeatureGroup } from "@/features/settings/components/providers/providerRows";

interface SearchStepProps {
  status: SetupStatus;
  catalog: ProviderCatalog;
  onSaved: () => void;
}

export function SearchStep({ status, catalog, onSaved }: SearchStepProps) {
  return (
    <m.div className="w-full rounded-2xl bg-zinc-900 p-4" {...MOTION_FADE_UP}>
      <FeatureProviderPicker
        group={resolveFeatureGroup("web_search", catalog, status)}
        catalog={catalog}
        status={status}
        onSaved={onSaved}
      />
    </m.div>
  );
}
