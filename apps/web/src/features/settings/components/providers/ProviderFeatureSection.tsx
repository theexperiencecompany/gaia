"use client";

import { useEffect, useRef } from "react";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { FeatureProviderPicker } from "@/features/settings/components/providers/FeatureProviderPicker";
import type { FeatureGroup } from "@/features/settings/components/providers/providerRows";
import { StatusBadge } from "@/features/settings/components/providers/StatusBadge";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";

interface ProviderFeatureSectionProps {
  group: FeatureGroup;
  catalog: ProviderCatalog;
  status: SetupStatus | undefined;
  /** Scroll this card into view: the page was opened to configure it. */
  isFocused: boolean;
  onSaved: () => void;
}

/** One feature's card: whether it works, then its provider picker. */
export function ProviderFeatureSection({
  group,
  catalog,
  status,
  isFocused,
  onSaved,
}: ProviderFeatureSectionProps) {
  const working = group.status?.working === true;
  const unavailable = group.status?.available === false;
  const sectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isFocused) {
      sectionRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }, [isFocused]);

  return (
    <div ref={sectionRef} className="scroll-mt-6">
      <SettingsSection
        title={group.spec.label}
        titleAccessory={
          group.status && (
            <StatusBadge
              label={unavailable ? "Unavailable" : working ? "Working" : "Off"}
              active={working}
            />
          )
        }
        description={group.spec.description}
      >
        <div className="px-4 py-3.5">
          <FeatureProviderPicker
            group={group}
            catalog={catalog}
            status={status}
            onSaved={onSaved}
          />
        </div>
      </SettingsSection>
    </div>
  );
}
