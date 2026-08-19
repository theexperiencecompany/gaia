"use client";

import { Button } from "@heroui/react";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import type { ModalAction } from "./SettingsMenu";

interface PreferencesDangerSectionProps {
  setModalAction: React.Dispatch<React.SetStateAction<ModalAction | null>>;
}

export function PreferencesDangerSection({
  setModalAction,
}: PreferencesDangerSectionProps) {
  return (
    <SettingsSection>
      <SettingsRow
        label="Clear Chat History"
        description="Permanently delete all your conversations and chat history"
        variant="danger"
      >
        <Button
          variant="flat"
          color="danger"
          onPress={() => setModalAction("clear_chats")}
        >
          Clear All
        </Button>
      </SettingsRow>
    </SettingsSection>
  );
}
