import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Tooltip } from "@heroui/tooltip";
import { SparklesIcon } from "@icons";
import { useState } from "react";
import {
  type Control,
  Controller,
  type FieldErrors,
  useWatch,
} from "react-hook-form";
import { toast } from "@/lib/toast";
import { workflowApi } from "../../api/workflowApi";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";

interface WorkflowDescriptionFieldProps {
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  mode?: "create" | "edit";
}

export default function WorkflowDescriptionField({
  control,
  errors,
  mode = "create",
}: WorkflowDescriptionFieldProps) {
  const [isGenerating, setIsGenerating] = useState(false);

  const [title, description, triggerConfig, currentPrompt] = useWatch({
    control,
    name: ["title", "description", "trigger_config", "prompt"],
  });

  const hasExistingPrompt = !!currentPrompt?.trim();

  const tooltipText = !title?.trim()
    ? "Add a title first"
    : hasExistingPrompt
      ? "Improve your instructions with AI"
      : "Generate instructions from your title & description";

  const handleGenerate = async (onChange: (val: string) => void) => {
    if (!title?.trim() || isGenerating) return;
    setIsGenerating(true);
    try {
      const result = await workflowApi.generatePrompt({
        title,
        description: description ?? undefined,
        trigger_config: triggerConfig as Record<string, unknown>,
        existing_prompt: hasExistingPrompt ? currentPrompt : undefined,
      });
      onChange(result.prompt);
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
                : "Describe in detail what this workflow should do when triggered, including specific actions and expected outcomes"
            }
            minRows={5}
            variant="underlined"
            className="text-sm"
            isRequired
            isInvalid={!!errors.prompt}
            errorMessage={errors.prompt?.message}
          />
          <div className="absolute top-1 right-0 opacity-0 group-hover:opacity-100 transition-opacity z-10">
            <Tooltip content={tooltipText} placement="top">
              <Button
                size="sm"
                variant="light"
                isIconOnly
                isDisabled={!title?.trim() || isGenerating}
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
