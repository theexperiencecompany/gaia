"use client";

import { useDisclosure } from "@heroui/react";
import { Skeleton } from "@heroui/skeleton";
import { NoteEditIcon } from "@icons";
import { ChevronRight } from "@/components/shared/icons";
import { useInstructions } from "@/features/instructions";
import type { Integration } from "@/features/integrations/types";
import { instructionsPreview } from "@/features/integrations/utils/instructionsPreview";

import { IntegrationInstructionsModal } from "./IntegrationInstructionsModal";

interface IntegrationInstructionsEditorProps {
  integration: Integration;
  toolNames: string[];
}

export const IntegrationInstructionsEditor = ({
  integration,
  toolNames,
}: IntegrationInstructionsEditorProps) => {
  const instructions = useInstructions(integration.id);
  const { isOpen, onOpen, onClose } = useDisclosure();

  const preview = instructionsPreview(instructions.instructions?.content ?? "");
  const subtitle = instructions.loadFailed
    ? "Couldn't load your instructions"
    : preview || `Teach GAIA how you use ${integration.name}`;

  if (instructions.isLoading) {
    return (
      <div className="flex w-full items-center gap-3 rounded-2xl bg-zinc-800/40 p-3">
        <Skeleton className="size-9 rounded-xl" />
        <div className="flex-1 space-y-1.5">
          <Skeleton className="h-3.5 w-32 rounded-lg" />
          <Skeleton className="h-3 w-44 rounded-lg" />
        </div>
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={onOpen}
        className="group flex w-full cursor-pointer items-center gap-3 rounded-2xl bg-zinc-800/40 p-3 text-left transition-colors hover:bg-zinc-800/60"
      >
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/15">
          <NoteEditIcon className="size-5 text-primary" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-zinc-100">
            Custom instructions
          </p>
          <p className="truncate text-xs text-zinc-500">{subtitle}</p>
        </div>
        <ChevronRight className="size-4 shrink-0 text-zinc-500 transition-transform group-hover:translate-x-0.5" />
      </button>

      <IntegrationInstructionsModal
        isOpen={isOpen}
        onClose={onClose}
        integration={integration}
        instructions={instructions}
        toolNames={toolNames}
      />
    </>
  );
};
