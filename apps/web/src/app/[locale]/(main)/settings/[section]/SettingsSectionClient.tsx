"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import type { ModalAction } from "@/features/settings/components/SettingsMenu";
import { SectionComponent } from "@/features/settings/config/sectionComponents";
import type { SettingsSection } from "@/features/settings/config/sectionKeys";
import { BILLING_ONLY_SETTINGS_KEYS } from "@/features/settings/config/settingsConfig";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";

interface SettingsSectionClientProps {
  readonly section: SettingsSection;
}

export default function SettingsSectionClient({
  section,
}: SettingsSectionClientProps) {
  const router = useRouter();
  const [modalAction, setModalAction] = useState<ModalAction | null>(null);
  const { data: setupStatus } = useSetupStatus();

  // Self-host instances have no billing — deep links to billing-only
  // sections redirect out instead of rendering.
  const billingHidden = setupStatus?.billing_enabled === false;

  useEffect(() => {
    if (billingHidden && BILLING_ONLY_SETTINGS_KEYS.has(section)) {
      router.replace("/settings/providers");
    }
  }, [billingHidden, section, router]);

  return (
    <>
      <div className="flex h-full w-full flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="flex w-full justify-center p-6">
            <div className="w-full">
              <SectionComponent
                section={section}
                setModalAction={setModalAction}
              />
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
