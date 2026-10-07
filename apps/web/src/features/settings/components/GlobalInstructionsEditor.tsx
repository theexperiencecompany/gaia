"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Skeleton } from "@heroui/skeleton";
import {
  GLOBAL_INSTRUCTIONS_SCOPE,
  InstructionsConflictNotice,
  MAX_INSTRUCTIONS_CHARS,
  useInstructions,
} from "@/features/instructions";

export const GlobalInstructionsEditor = () => {
  const {
    isLoading,
    loadFailed,
    draft,
    setDraft,
    isDirty,
    isSaving,
    isRefreshing,
    hasConflict,
    save,
    keepMine,
    loadLatest,
  } = useInstructions(GLOBAL_INSTRUCTIONS_SCOPE);

  return (
    <div className="flex flex-col gap-2">
      <div>
        <p className="text-sm text-white">Custom Instructions</p>
        <p className="mt-0.5 text-xs text-zinc-500">
          Included in every conversation.
        </p>
      </div>

      {isLoading ? (
        <Skeleton className="h-20 rounded-xl" />
      ) : (
        <Textarea
          aria-label="Custom instructions"
          placeholder="Add any specific instructions for how GAIA should assist you..."
          value={draft}
          onValueChange={setDraft}
          maxLength={MAX_INSTRUCTIONS_CHARS}
          minRows={3}
          classNames={{
            input: "bg-zinc-800/50 text-sm",
            inputWrapper: "bg-zinc-800/50 hover:bg-zinc-700/50",
          }}
        />
      )}

      {loadFailed && (
        <p className="text-xs text-red-400">
          Couldn't load your instructions. Refresh the page to try again.
        </p>
      )}

      {hasConflict && (
        <InstructionsConflictNotice
          isSaving={isSaving}
          isRefreshing={isRefreshing}
          onLoadLatest={loadLatest}
          onKeepMine={keepMine}
        />
      )}

      <div className="flex items-center justify-between">
        <span className="text-xs font-light text-zinc-500">
          {draft.length} / {MAX_INSTRUCTIONS_CHARS}
        </span>
        <Button
          size="sm"
          color="primary"
          onPress={save}
          isLoading={isSaving}
          isDisabled={!isDirty || hasConflict}
        >
          Save
        </Button>
      </div>
    </div>
  );
};
