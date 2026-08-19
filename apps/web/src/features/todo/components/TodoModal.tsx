"use client";

import { Button } from "@heroui/button";
import { Input, Textarea } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  Tooltip,
  useDisclosure,
} from "@heroui/react";
import { AlertCircleIcon, TaskAddIcon } from "@icons";
import { format } from "date-fns";
import { useEffect, useMemo } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
import { useTextProcessor } from "@/features/todo/hooks/useTextProcessor";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useModalForm } from "@/hooks/ui/useModalForm";
import { useModalKeyboardSubmit } from "@/hooks/ui/useModalKeyboardSubmit";
import { usePlatform } from "@/hooks/ui/usePlatform";
import {
  Priority,
  type Todo,
  type TodoCreate,
} from "@/types/features/todoTypes";

import RecurrenceFieldChip from "./fields/RecurrenceFieldChip";
import ScheduledFieldChip from "./fields/ScheduledFieldChip";
import SubtaskManager from "./shared/SubtaskManager";
import TodoFieldsRow from "./shared/TodoFieldsRow";

interface TodoModalProps {
  onSuccess?: () => void;
  mode: "add" | "edit";
  todo?: Todo;
  initialProjectId?: string;
  buttonText?: string;
  buttonClassName?: string;
}

function getChangedFields<T extends object>(
  original: T,
  updated: T,
): Partial<T> {
  const changes: Partial<T> = {};
  for (const key in updated) {
    const originalValue = original[key as keyof T];
    const updatedValue = updated[key as keyof T];
    const isEqual =
      typeof originalValue === "object"
        ? JSON.stringify(originalValue) === JSON.stringify(updatedValue)
        : originalValue === updatedValue;
    if (!isEqual) {
      changes[key as keyof T] = updatedValue;
    }
  }
  return changes;
}

interface TodoModalTriggerProps {
  buttonText: string;
  buttonClassName: string;
  onOpen: () => void;
}

function TodoModalTrigger({
  buttonText,
  buttonClassName,
  onOpen,
}: TodoModalTriggerProps) {
  return (
    <Tooltip
      content={
        <span className="flex items-center gap-2">
          {buttonText}
          <Kbd className="text-[10px]">C</Kbd>
        </span>
      }
      placement="right"
    >
      <Button
        className={buttonClassName}
        color="primary"
        size="sm"
        variant="flat"
        startContent={<TaskAddIcon className="h-4 w-4 outline-0" />}
        onPress={onOpen}
        data-keyboard-shortcut="create-todo"
      >
        {buttonText}
      </Button>
    </Tooltip>
  );
}

interface TodoTitleDescriptionFieldsProps {
  title: string;
  description?: string;
  onTitleChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
}

function TodoTitleDescriptionFields({
  title,
  description,
  onTitleChange,
  onDescriptionChange,
}: TodoTitleDescriptionFieldsProps) {
  return (
    <div className="flex flex-col">
      <Input
        placeholder="Title"
        classNames={{
          input:
            "text-2xl font-semibold bg-transparent border-0 text-zinc-100 placeholder:text-zinc-500",
          inputWrapper:
            "border-0 bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent",
        }}
        value={title}
        variant="underlined"
        onChange={(e) => onTitleChange(e.target.value)}
        required
        autoFocus
      />
      <Textarea
        placeholder="Add a description..."
        value={description || ""}
        onChange={(e) => onDescriptionChange(e.target.value)}
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
  );
}

interface TodoMetaFieldsProps {
  projectId?: string;
  projects: ReturnType<typeof useTodoData>["projects"];
  priority: Priority;
  dueDate?: string;
  dueDateTimezone?: string;
  labels: string[];
  scheduledAt?: string;
  recurrence?: TodoCreate["recurrence"];
  subtasks: TodoCreate["subtasks"];
  userTimezone?: string;
  mode: "add" | "edit";
  expiresAt?: string;
  onPriorityChange: (priority: Priority) => void;
  onProjectChange: (projectId?: string) => void;
  onDateChange: (date?: string, timezone?: string) => void;
  onLabelsChange: (labels: string[]) => void;
  onScheduledChange: (val?: string) => void;
  onRecurrenceChange: (val?: TodoCreate["recurrence"]) => void;
  onSubtasksChange: (subtasks: TodoCreate["subtasks"]) => void;
}

function TodoMetaFields({
  projectId,
  projects,
  priority,
  dueDate,
  dueDateTimezone,
  labels,
  scheduledAt,
  recurrence,
  subtasks,
  userTimezone,
  mode,
  expiresAt,
  onPriorityChange,
  onProjectChange,
  onDateChange,
  onLabelsChange,
  onScheduledChange,
  onRecurrenceChange,
  onSubtasksChange,
}: TodoMetaFieldsProps) {
  return (
    <>
      <TodoFieldsRow
        priority={priority ?? Priority.NONE}
        projectId={projectId}
        projects={projects}
        dueDate={dueDate}
        dueDateTimezone={dueDateTimezone}
        labels={labels ?? []}
        onPriorityChange={onPriorityChange}
        onProjectChange={onProjectChange}
        onDateChange={onDateChange}
        onLabelsChange={onLabelsChange}
        userTimezone={userTimezone}
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScheduledFieldChip
          value={scheduledAt ?? undefined}
          onChange={onScheduledChange}
          timezone={userTimezone}
        />
        <RecurrenceFieldChip
          value={recurrence ?? undefined}
          onChange={onRecurrenceChange}
        />
      </div>
      {mode === "edit" && expiresAt && (
        <div className="flex items-center gap-2 text-sm text-zinc-500">
          <AlertCircleIcon width={16} height={16} />
          <span>
            Expires {format(new Date(expiresAt), "EEE, MMM d 'at' h:mm a")}
          </span>
        </div>
      )}
      <SubtaskManager
        subtasks={subtasks || []}
        onSubtasksChange={onSubtasksChange}
      />
    </>
  );
}

interface TodoModalFooterProps {
  onClose: () => void;
  onSubmit: () => void;
  loading: boolean;
  mode: "add" | "edit";
  modifierKeyName: string;
}

function TodoModalFooter({
  onClose,
  onSubmit,
  loading,
  mode,
  modifierKeyName,
}: TodoModalFooterProps) {
  return (
    <ModalFooter>
      <Button variant="light" onPress={onClose}>
        Cancel
      </Button>
      <Button
        color="primary"
        onPress={onSubmit}
        isDisabled={loading}
        isLoading={loading}
        endContent={
          !loading && (
            <Kbd keys={[modifierKeyName as "command" | "ctrl", "enter"]} />
          )
        }
      >
        {mode === "edit" ? "Save Changes" : "Add Task"}
      </Button>
    </ModalFooter>
  );
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
  const { isMac, modifierKeyName } = usePlatform();
  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const { projects, createTodo, updateTodo } = useTodoData({ autoLoad: false });
  const userTimezone = user?.timezone;
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
        scheduled_at: todo.scheduled_at,
        recurrence: todo.recurrence,
        subtasks: todo.subtasks || [],
      };
    }
    return {
      title: "",
      description: "",
      labels: [] as string[],
      priority: Priority.NONE,
      project_id: initialProjectId,
      scheduled_at: undefined,
      recurrence: undefined,
      subtasks: [] as TodoCreate["subtasks"],
    };
  }, [mode, todo, initialProjectId]);
  const { formData, setFormData, loading, handleSubmit, updateField } =
    useModalForm<TodoCreate>({
      initialData,
      onSubmit: async (data: TodoCreate) => {
        if (mode === "edit" && todo) {
          const updates = getChangedFields(todo, data);
          if (Object.keys(updates).length > 0) {
            await updateTodo(todo.id, updates);
          }
          return;
        }
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
  useEffect(() => {
    if (mode === "add" && initialProjectId) {
      updateField("project_id", initialProjectId);
    }
  }, [mode, initialProjectId, updateField]);
  useEffect(() => {
    if (
      isOpen &&
      mode === "add" &&
      projects.length > 0 &&
      !formData.project_id
    ) {
      const inboxProject = projects.find(
        (p: (typeof projects)[number]) => p.is_default,
      );
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
  ]);
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
        scheduled_at: todo.scheduled_at,
        recurrence: todo.recurrence,
        subtasks: todo.subtasks || [],
      });
    }
  }, [isOpen, mode, todo, setFormData]);
  useModalKeyboardSubmit({ isOpen, loading, isMac, handleSubmit });
  const handleDateChange = (date?: string, timezone?: string) => {
    setFormData((prev: TodoCreate) => ({
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
    const hasPatterns = Object.keys(commands).length > 0;
    if (hasPatterns && cleanText !== text) {
      updateField(field, cleanText);
    }
    if (commands.project?.id) {
      updateField("project_id", commands.project.id);
    }
    if (commands.labels && commands.labels.length > 0) {
      const uniqueLabels = [
        ...new Set([...(formData.labels ?? []), ...commands.labels]),
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
  const handleTitleChange = (value: string) => {
    updateField("title", value);
    handleTextProcessing(value, "title");
  };
  const handleDescriptionChange = (value: string) => {
    updateField("description", value);
    handleTextProcessing(value, "description");
  };
  return (
    <>
      <TodoModalTrigger
        buttonText={buttonText}
        buttonClassName={buttonClassName}
        onOpen={onOpen}
      />
      <Modal isOpen={isOpen} onOpenChange={onOpenChange} size="lg">
        <ModalContent>
          {(onClose) => (
            <>
              <ModalBody className="gap-6 pt-6">
                <TodoTitleDescriptionFields
                  title={formData.title}
                  description={formData.description}
                  onTitleChange={handleTitleChange}
                  onDescriptionChange={handleDescriptionChange}
                />
                <TodoMetaFields
                  projectId={formData.project_id}
                  projects={projects}
                  priority={formData.priority ?? Priority.NONE}
                  dueDate={formData.due_date}
                  dueDateTimezone={formData.due_date_timezone}
                  labels={formData.labels ?? []}
                  scheduledAt={formData.scheduled_at ?? undefined}
                  recurrence={formData.recurrence ?? undefined}
                  subtasks={formData.subtasks || []}
                  userTimezone={userTimezone}
                  mode={mode}
                  expiresAt={todo?.expires_at ?? undefined}
                  onPriorityChange={(priority) =>
                    updateField("priority", priority)
                  }
                  onProjectChange={(projectId) =>
                    updateField("project_id", projectId)
                  }
                  onDateChange={handleDateChange}
                  onLabelsChange={(labels) => updateField("labels", labels)}
                  onScheduledChange={(scheduledAt) =>
                    updateField("scheduled_at", scheduledAt)
                  }
                  onRecurrenceChange={(val) => updateField("recurrence", val)}
                  onSubtasksChange={(subtasks) =>
                    updateField("subtasks", subtasks)
                  }
                />
              </ModalBody>
              <TodoModalFooter
                onClose={onClose}
                onSubmit={handleSubmit}
                loading={loading}
                mode={mode}
                modifierKeyName={modifierKeyName}
              />
            </>
          )}
        </ModalContent>
      </Modal>
    </>
  );
}
