"use client";

import { Alert, Button } from "@heroui/react";

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
      <Button
        size="sm"
        variant="secondary"
        onPress={onLoadLatest}
        isPending={isRefreshing}
        isDisabled={isSaving}
      >
        Load latest
      </Button>
      <Button
        size="sm"
        variant="danger-soft"
        onPress={onKeepMine}
        isPending={isSaving}
        isDisabled={isRefreshing}
      >
        Keep mine
      </Button>
    </div>
  </Alert>
);
