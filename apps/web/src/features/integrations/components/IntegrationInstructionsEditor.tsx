"use client";

import { Button } from "@heroui/button";
import { useDisclosure } from "@heroui/react";
import { Spinner } from "@heroui/spinner";
import { Edit02Icon } from "@icons";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { useIntegrationInstructions } from "@/features/integrations/hooks/useIntegrationInstructions";

import { IntegrationInstructionsModal } from "./IntegrationInstructionsModal";

interface IntegrationInstructionsEditorProps {
  integrationId: string;
  integrationName: string;
}

export const IntegrationInstructionsEditor = ({
  integrationId,
  integrationName,
}: IntegrationInstructionsEditorProps) => {
  const { instructions, isLoading, isSaving, save } =
    useIntegrationInstructions(integrationId);
  const { isOpen, onOpen, onClose } = useDisclosure();

  const content = instructions?.content ?? "";
  const hasContent = content.trim().length > 0;
  const editedBy = instructions?.updatedBy === "agent" ? "GAIA" : "you";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-300">
          Custom instructions
        </h2>
        {hasContent && instructions?.updatedAt && (
          <span className="text-xs font-light text-zinc-500">
            Last edited by {editedBy}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-6">
          <Spinner size="sm" />
        </div>
      ) : hasContent ? (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={onOpen}
            className="relative max-h-32 overflow-hidden rounded-2xl bg-zinc-800 p-3 text-left transition-colors hover:bg-zinc-700/70"
          >
            <MarkdownRenderer
              content={content}
              className="pointer-events-none text-sm"
            />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-zinc-800 to-transparent" />
          </button>
          <Button
            size="sm"
            variant="flat"
            className="self-end"
            startContent={<Edit02Icon width={16} height={16} />}
            onPress={onOpen}
          >
            Edit
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={onOpen}
          className="flex flex-col items-start gap-1 rounded-2xl border border-dashed border-zinc-700 bg-zinc-800/40 p-4 text-left transition-colors hover:border-zinc-600 hover:bg-zinc-800/70"
        >
          <span className="text-sm font-medium text-zinc-300">
            Add custom instructions
          </span>
          <span className="text-xs font-light text-zinc-500">
            Standing guidance GAIA follows whenever it uses {integrationName} —
            like which channels or projects to focus on, or defaults to apply.
          </span>
        </button>
      )}

      <IntegrationInstructionsModal
        isOpen={isOpen}
        onClose={onClose}
        integrationName={integrationName}
        savedContent={content}
        isSaving={isSaving}
        onSave={save}
      />
    </div>
  );
};
