"use client";

import { useState } from "react";
import type { ConfirmAction } from "@/components/shared/ConfirmActionDialog";
import { ConfirmActionDialog } from "@/components/shared/ConfirmActionDialog";
import type { ModalAction } from "@/features/settings/components/SettingsMenu";
import { SectionComponent } from "@/features/settings/config/sectionComponents";
import type { SettingsSection } from "@/features/settings/config/sectionKeys";

interface SettingsSectionClientProps {
  section: SettingsSection;
}

export default function SettingsSectionClient({
  section,
}: SettingsSectionClientProps) {
  const [modalAction, setModalAction] = useState<ModalAction | null>(null);

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
        action={modalAction as ConfirmAction}
        onOpenChange={(action) => setModalAction(action as ModalAction)}
      />
    </>
  );
}
