import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { SparklesIcon } from "@icons";
import { useMemo, useState } from "react";
import {
  type Control,
  Controller,
  type FieldErrors,
  type UseFormSetValue,
  useWatch,
} from "react-hook-form";
import { TextMorph } from "torph/react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { MentionEditor } from "@/features/integrations/components/MentionEditor";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { getUserHomeTimezone } from "@/lib/timezone";
import { toast } from "@/lib/toast";
import { workflowApi } from "../../api/workflowApi";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";
import { mentionableIntegrations } from "../../utils/integrationMentions";
import WorkflowSection from "./WorkflowSection";

interface WorkflowDescriptionFieldProps {
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  setValue?: UseFormSetValue<WorkflowFormData>;
  isPreview?: boolean;
  selectedIntegrationSlugs: string[];
}

export default function WorkflowDescriptionField({
  control,
  errors,
  setValue,
  isPreview = false,
  selectedIntegrationSlugs,
}: WorkflowDescriptionFieldProps) {
  const [isGenerating, setIsGenerating] = useState(false);

  const { integrations } = useIntegrations();
  // Only integrations the user can actually use are mentionable.
  const mentionable = useMemo(
    () => mentionableIntegrations(integrations),
    [integrations],
  );
  const toolNames = useMemo(
    () => mentionable.map((i) => i.name),
    [mentionable],
  );
  const integrationByName = useMemo(
    () => new Map(mentionable.map((i) => [i.name, i])),
    [mentionable],
  );
  const renderMentionIcon = (name: string) => {
    const integ = integrationByName.get(name);
    if (!integ) return null;
    return getToolCategoryIcon(
      integ.id,
      { size: 14, width: 14, height: 14, showBackground: false },
      integ.iconUrl,
    );
  };

  const [title, description, triggerConfig, currentPrompt] = useWatch({
    control,
    name: ["title", "description", "trigger_config", "prompt"],
  });

  const hasExistingPrompt = !!currentPrompt?.trim();

  const handleGenerate = async () => {
    if (isGenerating || !setValue) return;
    setIsGenerating(true);
    try {
      const result = await workflowApi.generatePrompt({
        title: title?.trim() || undefined,
        description: description ?? undefined,
        trigger_config: triggerConfig as Record<string, unknown>,
        existing_prompt: hasExistingPrompt ? currentPrompt : undefined,
        selected_integrations:
          selectedIntegrationSlugs.length > 0
            ? selectedIntegrationSlugs
            : undefined,
      });
      setValue("prompt", result.prompt, { shouldDirty: true });

      // Auto-fill trigger config from AI suggestion
      if (result.suggested_trigger) {
        const { type, cron_expression, trigger_name } =
          result.suggested_trigger;

        if (type === "schedule") {
          setValue("activeTab", "schedule");
          setValue("trigger_config", {
            type: "schedule",
            enabled: true,
            cron_expression: cron_expression || "0 9 * * *",
            timezone: getUserHomeTimezone(),
          });
        } else if (type === "manual") {
          setValue("activeTab", "manual");
          setValue("trigger_config", { type: "manual", enabled: true });
        } else if (type === "integration" && trigger_name) {
          setValue("activeTab", "trigger");
          setValue("selectedTrigger", trigger_name);
          setValue("trigger_config", {
            type: "integration",
            enabled: true,
            trigger_name,
            trigger_data: { trigger_name },
          });
        }
      }
    } catch {
      toast.error("Failed to generate instructions");
    } finally {
      setIsGenerating(false);
    }
  };

  // Generation needs something to work from — a title, a description, or an
  // existing prompt to improve. With a blank form there's nothing to generate.
  const canGenerate = !!(
    title?.trim() ||
    description?.trim() ||
    currentPrompt?.trim()
  );

  const generateButton = !isPreview ? (
    <Tooltip
      content="Add a title, description, or instructions first"
      placement="top"
      isDisabled={canGenerate}
    >
      {/* span wrapper keeps the tooltip hoverable while the button is disabled */}
      <span className="inline-flex">
        <Button
          size="sm"
          variant="light"
          color="primary"
          className="h-7 px-2 text-xs"
          startContent={!isGenerating && <SparklesIcon className="h-4 w-4" />}
          isLoading={isGenerating}
          isDisabled={isGenerating || !canGenerate}
          onPress={handleGenerate}
        >
          <TextMorph duration={300}>
            {hasExistingPrompt ? "Improve with AI" : "Generate with AI"}
          </TextMorph>
        </Button>
      </span>
    </Tooltip>
  ) : undefined;

  return (
    <WorkflowSection label="Instructions" action={generateButton}>
      <Controller
        name="prompt"
        control={control}
        render={({ field }) => (
          <>
            <MentionEditor
              value={field.value ?? ""}
              onChange={field.onChange}
              toolNames={toolNames}
              renderMentionIcon={renderMentionIcon}
              mentionRadius="sm"
              readOnly={isPreview}
              placeholder="E.g.: Every morning, check my unread emails for action items, review my calendar, then send me a 3-bullet briefing via @Slack"
              className={`relative rounded-xl bg-zinc-800/60 transition-colors focus-within:bg-zinc-800/80 ${
                errors.prompt ? "ring-1 ring-danger" : ""
              }`}
              surfaceClassName="min-h-28 max-h-72"
            />
            {errors.prompt?.message && (
              <p className="mt-1.5 px-1 text-xs text-danger">
                {errors.prompt.message}
              </p>
            )}
          </>
        )}
      />
    </WorkflowSection>
  );
}
