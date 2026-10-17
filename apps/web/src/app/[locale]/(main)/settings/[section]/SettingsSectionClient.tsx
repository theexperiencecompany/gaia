"use client";

import { RedirectType, redirect } from "next/navigation";
import { useState } from "react";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import type { ModalAction } from "@/features/settings/components/SettingsMenu";
import { SectionComponent } from "@/features/settings/config/sectionComponents";
import {
  DEFAULT_SECTION,
  type SettingsSection,
} from "@/features/settings/config/sectionKeys";
import {
  BILLING_ONLY_SETTINGS_KEYS,
  isSettingsSectionAllowed,
} from "@/features/settings/config/settingsConfig";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";

interface SettingsSectionClientProps {
  readonly section: SettingsSection;
}

export default function SettingsSectionClient({
  section,
}: SettingsSectionClientProps) {
  const [modalAction, setModalAction] = useState<ModalAction | null>(null);

  // Self-host instances have no billing — deep links to billing-only
  // sections redirect out instead of rendering.
  const billingHidden = !useDeployment().bills;
  // Render a role-gated section only once the role allows it; redirect once
  // the account is known (an empty userId means not yet) and it does not.
  const { userId, role } = useCurrentUser();
  const allowed = isSettingsSectionAllowed(section, role);
  const forbidden = userId !== "" && !allowed;

  // Resolved during render, not an effect, so the blocked section never paints.
  if (billingHidden && BILLING_ONLY_SETTINGS_KEYS.has(section)) {
    redirect("/settings/providers", RedirectType.replace);
  }
  if (forbidden) {
    redirect(`/settings/${DEFAULT_SECTION}`, RedirectType.replace);
  }

  return (
    <>
      <div className="flex h-full w-full flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="flex w-full justify-center p-6">
            <div className="w-full">
              {allowed && (
                <SectionComponent
                  section={section}
                  setModalAction={setModalAction}
                />
              )}
            </div>
          </div>
        </div>
      </div>

      <ConfirmActionDialog
        action={modalAction}
        onOpenChange={(action) => setModalAction(action as ModalAction)}
      />
    </>
  );
}
