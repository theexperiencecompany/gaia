"use client";

import { Button } from "@heroui/button";
import { Alert } from "@heroui/react";

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
  <Alert
    color="warning"
    variant="flat"
    title="These instructions changed since you opened them"
    description="GAIA may have updated them while you were editing. Load the latest version, or keep yours to overwrite it."
    endContent={
      <div className="flex shrink-0 gap-2">
        <Button
          size="sm"
          variant="flat"
          onPress={onLoadLatest}
          isLoading={isRefreshing}
          isDisabled={isSaving}
        >
          Load latest
        </Button>
        <Button
          size="sm"
          color="warning"
          variant="flat"
          onPress={onKeepMine}
          isLoading={isSaving}
          isDisabled={isRefreshing}
        >
          Keep mine
        </Button>
      </div>
    }
  />
);
