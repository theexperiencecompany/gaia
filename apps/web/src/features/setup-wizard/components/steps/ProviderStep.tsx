/**
 * Wizard step 1 — pick and configure an AI provider through the same picker
 * Settings uses: one provider select, then only that provider's fields. Any
 * single saved provider unblocks continuing.
 */

"use client";

import * as m from "motion/react-m";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { FeatureProviderPicker } from "@/features/settings/components/providers/FeatureProviderPicker";
import { resolveFeatureGroup } from "@/features/settings/components/providers/providerRows";
import { MOTION_FADE_UP } from "../../constants";

interface ProviderStepProps {
  status: SetupStatus;
  catalog: ProviderCatalog;
  /** Refetch setup status after a save, so Continue and Done reflect it. */
  onSaved: () => void;
}

export function ProviderStep({ status, catalog, onSaved }: ProviderStepProps) {
  return (
    <m.div className="w-full rounded-2xl bg-zinc-900 p-4" {...MOTION_FADE_UP}>
      <FeatureProviderPicker
        group={resolveFeatureGroup("ai_models", catalog, status)}
        catalog={catalog}
        status={status}
        onSaved={onSaved}
      />
    </m.div>
  );
}
