import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Tooltip } from "@heroui/tooltip";
import { SparklesIcon } from "@icons";
import { useState } from "react";
import {
  type Control,
  Controller,
  type FieldErrors,
  type UseFormSetValue,
  useWatch,
} from "react-hook-form";
import { toast } from "@/lib/toast";
import { workflowApi } from "../../api/workflowApi";
import {
  getBrowserTimezone,
  type WorkflowFormData,
} from "../../schemas/workflowFormSchema";

interface WorkflowDescriptionFieldProps {
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  setValue?: UseFormSetValue<WorkflowFormData>;
  mode?: "create" | "edit";
}

export default function WorkflowDescriptionField({
  control,
  errors,
  setValue,
  mode = "create",
}: WorkflowDescriptionFieldProps) {
  const [isGenerating, setIsGenerating] = useState(false);

  const [title, description, triggerConfig, currentPrompt] = useWatch({
    control,
    name: ["title", "description", "trigger_config", "prompt"],
  });

  const hasExistingPrompt = !!currentPrompt?.trim();

  const tooltipText = isGenerating
    ? "Generating..."
    : hasExistingPrompt
      ? "Improve instructions and triggers with AI"
      : "Generate instructions and triggers with AI";

  const handleGenerate = async (onChange: (val: string) => void) => {
    if (isGenerating) return;
    setIsGenerating(true);
    try {
      const result = await workflowApi.generatePrompt({
        title: title?.trim() || undefined,
        description: description ?? undefined,
        trigger_config: triggerConfig as Record<string, unknown>,
        existing_prompt: hasExistingPrompt ? currentPrompt : undefined,
      });
      onChange(result.prompt);

      // Auto-fill trigger config from AI suggestion
      if (result.suggested_trigger && setValue) {
        const { type, cron_expression, trigger_name } =
          result.suggested_trigger;

        if (type === "schedule") {
          setValue("activeTab", "schedule");
          setValue("trigger_config", {
            type: "schedule",
            enabled: true,
            cron_expression: cron_expression || "0 9 * * *",
            timezone: getBrowserTimezone(),
          });
        } else if (type === "manual") {
          setValue("activeTab", "manual");
          setValue("trigger_config", { type: "manual", enabled: true });
        } else if (type === "integration") {
          setValue("activeTab", "trigger");
          if (trigger_name) {
            setValue("selectedTrigger", trigger_name);
            setValue("trigger_config", {
              type: "integration",
              enabled: true,
              trigger_name,
              trigger_data: { trigger_name },
            });
          }
        }
      }
    } catch {
      toast.error("Failed to generate instructions");
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <Controller
      name="prompt"
      control={control}
      render={({ field }) => (
        <div className="relative group">
          <Textarea
            {...field}
            label="Instructions"
            placeholder={
              mode === "edit"
                ? "Detailed instructions for what this workflow should do"
                : "Describe in detail what this workflow should do when triggered"
            }
            minRows={5}
            variant="underlined"
            className="text-sm"
            isRequired
            isInvalid={!!errors.prompt}
            errorMessage={errors.prompt?.message}
          />
          <div className="absolute top-1 right-0 z-10">
            <Tooltip content={tooltipText} placement="top">
              <Button
                size="sm"
                variant="light"
                isIconOnly
                isDisabled={isGenerating}
                isLoading={isGenerating}
                onPress={() => handleGenerate(field.onChange)}
                className="text-foreground-400 hover:text-primary"
              >
                {!isGenerating && <SparklesIcon className="h-4 w-4" />}
              </Button>
            </Tooltip>
          </div>
        </div>
      )}
    />
  );
}
