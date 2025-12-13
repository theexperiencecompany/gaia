"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  useDisclosure,
} from "@heroui/react";
import { useEffect, useMemo } from "react";

import { useUser } from "@/features/auth/hooks/useUser";
import { useTextProcessor } from "@/features/todo/hooks/useTextProcessor";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useModalForm } from "@/hooks/ui/useModalForm";
import { PlusSignIcon } from "@/icons";
import { posthog } from "@/lib";
import {
  Priority,
  type Todo,
  type TodoCreate,
} from "@/types/features/todoTypes";

import SubtaskManager from "./shared/SubtaskManager";
import TodoFieldsRow from "./shared/TodoFieldsRow";

interface TodoModalProps {
  onSuccess?: () => void;
  mode: "add" | "edit";
  todo?: Todo; // Required when mode is "edit"
  initialProjectId?: string; // Used when mode is "add"
  buttonText?: string;
  buttonClassName?: string;
}

function getChangedFields<T extends object>(
  original: T,
  updated: T,
): Partial<T> {
  const changes: Partial<T> = {};

  for (const key in updated) {
    const originalValue = original[key];
    const updatedValue = updated[key];

    const isEqual =
      typeof originalValue === "object"
        ? JSON.stringify(originalValue) === JSON.stringify(updatedValue)
        : originalValue === updatedValue;

    if (!isEqual) {
      changes[key] = updatedValue;
    }
  }

  return changes;
}

export default function TodoModal({
  onSuccess,
  mode,
  todo,
  initialProjectId,
  buttonText = "Add Task",
  buttonClassName = "w-full justify-start text-sm text-primary",
}: TodoModalProps) {
  const user = useUser();
  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const { projects, createTodo, updateTodo } = useTodoData({ autoLoad: false });

  // Get user's preferred timezone or fallback to browser timezone
  const userTimezone = user?.timezone;

  // Initialize text processor
  const { processText } = useTextProcessor({
    projects,
    userTimezone,
  });

  const initialData = useMemo(() => {
    if (mode === "edit" && todo) {
      return {
        title: todo.title,
        description: todo.description,
        labels: todo.labels,
        priority: todo.priority,
        project_id: todo.project_id,
        due_date: todo.due_date,
        due_date_timezone: todo.due_date_timezone,
        subtasks: todo.subtasks || [],
      };
    }

    return {
      title: "",
      description: "",
      labels: [],
      priority: Priority.NONE,
      project_id: initialProjectId,
      subtasks: [],
    };
  }, [mode, todo, initialProjectId]);

  const { formData, setFormData, loading, handleSubmit, updateField } =
    useModalForm<TodoCreate>({
      initialData,
      onSubmit: async (data: TodoCreate) => {
        if (mode === "edit" && todo) {
          const updates = getChangedFields(todo, data);

          if (Object.keys(updates).length > 0) {
            // Track todo update
            posthog.capture("todos:updated", {
              todo_id: todo.id,
              fields_changed: Object.keys(updates),
              has_due_date: !!data.due_date,
              priority: data.priority,
              has_subtasks: (data.subtasks?.length || 0) > 0,
            });
            await updateTodo(todo.id, updates);
          }
          return;
        }

        // Track todo creation
        posthog.capture("todos:created", {
          has_description: !!data.description,
          has_due_date: !!data.due_date,
          priority: data.priority,
          labels_count: data.labels?.length || 0,
          has_project: !!data.project_id,
          subtasks_count: data.subtasks?.length || 0,
        });

        await createTodo(data);
      },
      validate: [
        {
          field: "title",
          required: true,
          message: "Please enter a task title",
        },
      ],
      onSuccess: () => {
        onOpenChange();
        onSuccess?.();
      },
      resetOnSuccess: mode === "add",
    });

  // Set initial project ID when it changes (add mode)
  useEffect(() => {
    if (mode === "add" && initialProjectId) {
      updateField("project_id", initialProjectId);
    }
  }, [mode, initialProjectId, updateField]);

  // Set default project when modal opens in add mode
  useEffect(() => {
    if (
      isOpen &&
      mode === "add" &&
      projects.length > 0 &&
      !formData.project_id
    ) {
      const inboxProject = projects.find((p) => p.is_default);
      if (inboxProject) {
        updateField("project_id", inboxProject.id);
      }
    }
  }, [
    isOpen,
    mode,
    projects.length,
    updateField,
    formData.project_id,
    projects,
  ]); // Only run when modal opens

  // Reset form data when modal opens with todo (edit mode)
  useEffect(() => {
    if (isOpen && mode === "edit" && todo) {
      setFormData({
        title: todo.title,
        description: todo.description,
        labels: todo.labels,
        priority: todo.priority,
        project_id: todo.project_id,
        due_date: todo.due_date,
        due_date_timezone: todo.due_date_timezone,
        subtasks: todo.subtasks || [],
      });
    }
  }, [isOpen, mode, todo, setFormData]);

  const handleDateChange = (date?: string, timezone?: string) => {
    setFormData((prev) => ({
      ...prev,
      due_date: date,
      due_date_timezone: timezone,
    }));
  };

  const handleTextProcessing = (
    text: string,
    field: "title" | "description",
  ) => {
    const { cleanText, commands } = processText(text);

    // Only update the field if patterns were found and text changed
    const hasPatterns = Object.keys(commands).length > 0;
    if (hasPatterns && cleanText !== text) {
      updateField(field, cleanText);
    }

    // Apply commands to update other fields
    if (commands.project?.id) {
      updateField("project_id", commands.project.id);
    }

    if (commands.labels && commands.labels.length > 0) {
      // Avoid duplicate labels
      const uniqueLabels = [
        ...new Set([...formData.labels, ...commands.labels]),
      ];
      updateField("labels", uniqueLabels);
    }

    if (commands.priority) {
      updateField("priority", commands.priority);
    }

    if (commands.dueDate) {
      updateField("due_date", commands.dueDate.date);
      updateField("due_date_timezone", commands.dueDate.timezone);
    }
  };

  return (
    <>
      <Button
        className={buttonClassName}
        color="primary"
        size="sm"
        variant="flat"
        startContent={<PlusSignIcon className="h-4 w-4 outline-0" />}
        onPress={onOpen}
      >
        {buttonText}
      </Button>

      <Modal
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        size="lg"
        // isDismissable={false}
        // isKeyboardDismissDisabled={true}
        // hideCloseButton
      >
        <ModalContent>
          {(onClose) => (
            <>
              <ModalBody className="gap-6 pt-6">
                <div className="flex flex-col">
                  <Input
                    placeholder="Title"
                    classNames={{
                      input:
                        "text-2xl font-semibold bg-transparent border-0 text-zinc-100 placeholder:text-zinc-500",
                      inputWrapper:
                        "border-0 bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent",
                    }}
                    value={formData.title}
                    variant="underlined"
                    onChange={(e) => {
                      const value = e.target.value;
                      updateField("title", value);
                      handleTextProcessing(value, "title");
                    }}
                    required
                    autoFocus
                  />

                  {/* Description */}
                  <Textarea
                    placeholder="Add a description..."
                    value={formData.description || ""}
                    onChange={(e) => {
                      const value = e.target.value;
                      updateField("description", value);
                      handleTextProcessing(value, "description");
                    }}
                    minRows={1}
                    maxRows={5}
                    variant="underlined"
                    classNames={{
                      input:
                        "bg-transparent border-0 text-zinc-200 placeholder:text-zinc-500",
                      inputWrapper:
                        "border-0 bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent",
                    }}
                  />
                </div>

                {/* Fields Row with Chips */}
                <TodoFieldsRow
                  priority={formData.priority}
                  projectId={formData.project_id}
                  projects={projects}
                  dueDate={formData.due_date}
                  dueDateTimezone={formData.due_date_timezone}
                  labels={formData.labels}
                  onPriorityChange={(priority) =>
                    updateField("priority", priority)
                  }
                  onProjectChange={(projectId) =>
                    updateField("project_id", projectId)
                  }
                  onDateChange={handleDateChange}
                  onLabelsChange={(labels) => updateField("labels", labels)}
                  userTimezone={userTimezone}
                />

                {/* Subtasks Manager */}
                <SubtaskManager
                  subtasks={formData.subtasks || []}
                  onSubtasksChange={(subtasks) =>
                    updateField("subtasks", subtasks)
                  }
                />
              </ModalBody>

              <ModalFooter>
                <Button variant="light" onPress={onClose}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  onPress={handleSubmit}
                  isDisabled={loading}
                  isLoading={loading}
                >
                  {mode === "edit" ? "Save Changes" : "Add Task"}
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </>
  );
}
