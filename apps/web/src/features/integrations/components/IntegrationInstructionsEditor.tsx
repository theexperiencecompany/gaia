"use client";

import { Button } from "@heroui/button";
import { useDisclosure } from "@heroui/react";
import { Add01Icon, PencilEdit02Icon } from "@icons";
import { useIntegrationInstructions } from "@/features/integrations/hooks/useIntegrationInstructions";

import { IntegrationInstructionsModal } from "./IntegrationInstructionsModal";

interface IntegrationInstructionsEditorProps {
  integrationId: string;
  integrationName: string;
  toolNames: string[];
}

export const IntegrationInstructionsEditor = ({
  integrationId,
  integrationName,
  toolNames,
}: IntegrationInstructionsEditorProps) => {
  const { instructions, isLoading, isSaving, save } =
    useIntegrationInstructions(integrationId);
  const { isOpen, onOpen, onClose } = useDisclosure();

  const hasContent = (instructions?.content ?? "").trim().length > 0;

  return (
    <>
      <Button
        size="sm"
        variant="flat"
        radius="full"
        isLoading={isLoading}
        isDisabled={isLoading}
        onPress={onOpen}
        startContent={
          !isLoading &&
          (hasContent ? (
            <PencilEdit02Icon width={15} height={15} />
          ) : (
            <Add01Icon width={15} height={15} />
          ))
        }
        className="text-zinc-300"
      >
        {hasContent ? "Edit custom instructions" : "Add custom instructions"}
      </Button>

      <IntegrationInstructionsModal
        isOpen={isOpen}
        onClose={onClose}
        integrationName={integrationName}
        savedContent={instructions?.content ?? ""}
        isSaving={isSaving}
        toolNames={toolNames}
        onSave={save}
      />
    </>
  );
};
