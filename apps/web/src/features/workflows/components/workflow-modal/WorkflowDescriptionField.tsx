import { Textarea } from "@heroui/input";
import { type Control, Controller, type FieldErrors } from "react-hook-form";
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
  return (
    <Controller
      name="description"
      control={control}
      render={({ field }) => (
        <Textarea
          {...field}
          placeholder={
            mode === "edit"
              ? "Edit workflow description"
              : "Describe what this workflow should do when triggered"
          }
          minRows={7}
          variant="underlined"
          className="text-sm mb-1"
          isRequired
          isInvalid={!!errors.description}
          errorMessage={errors.description?.message}
        />
      )}
    />
  );
}
