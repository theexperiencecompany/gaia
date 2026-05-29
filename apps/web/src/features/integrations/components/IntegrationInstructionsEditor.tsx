"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Spinner } from "@heroui/spinner";
import { useEffect, useState } from "react";
import { useIntegrationInstructions } from "@/features/integrations/hooks/useIntegrationInstructions";

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
  const [value, setValue] = useState("");

  const saved = instructions?.content ?? "";
  // Re-sync the editor whenever the saved content changes (initial load or an
  // agent-side update arriving via refetch).
  useEffect(() => {
    setValue(saved);
  }, [saved]);

  const isDirty = value.trim() !== saved.trim();

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-300">
          Custom instructions
        </h2>
        {instructions?.updatedAt && (
          <span className="text-xs font-light text-zinc-500">
            Last edited by {instructions.updatedBy === "agent" ? "GAIA" : "you"}
          </span>
        )}
      </div>
      <p className="text-xs font-light text-zinc-500">
        Standing guidance GAIA follows whenever it uses {integrationName} — like
        which channels or projects to focus on, or defaults to apply.
      </p>
      {isLoading ? (
        <div className="flex justify-center py-4">
          <Spinner size="sm" />
        </div>
      ) : (
        <>
          <Textarea
            value={value}
            onValueChange={setValue}
            minRows={4}
            maxRows={12}
            variant="bordered"
            placeholder={`e.g. Focus on #eng, #design, and #pm. Never post to #general.`}
          />
          <Button
            color="primary"
            size="sm"
            className="self-end"
            isLoading={isSaving}
            isDisabled={!isDirty || isSaving}
            onPress={() => save(value)}
          >
            Save
          </Button>
        </>
      )}
    </div>
  );
};
