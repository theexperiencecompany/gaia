"use client";

import { Alert } from "@heroui/react";
import { GaiaButton } from "@/components/shared/GaiaButton";

interface InstructionsConflictNoticeProps {
  isSaving: boolean;
  isRefreshing: boolean;
  onLoadLatest: () => void;
  onKeepMine: () => void;
}

export const InstructionsConflictNotice = ({
  isSaving,
  isRefreshing,
  onLoadLatest,
  onKeepMine,
}: InstructionsConflictNoticeProps) => (
  <Alert status="warning">
    <Alert.Indicator />
    <Alert.Content>
      <Alert.Title>
        These instructions changed since you opened them
      </Alert.Title>
      <Alert.Description>
        GAIA may have updated them while you were editing. Load the latest
        version, or keep yours to overwrite it.
      </Alert.Description>
    </Alert.Content>
    <div className="flex shrink-0 gap-2">
      <GaiaButton
        size="sm"
        variant="secondary"
        onPress={onLoadLatest}
        isPending={isRefreshing}
        isDisabled={isSaving}
      >
        Load latest
      </GaiaButton>
      <GaiaButton
        variant="warning-soft"
        size="sm"
        onPress={onKeepMine}
        isPending={isSaving}
        isDisabled={isRefreshing}
      >
        Keep mine
      </GaiaButton>
    </div>
  </Alert>
);
