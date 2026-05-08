import { parseQuickAdd } from "@gaia/shared/utils";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { View } from "react-native";
import { notificationHaptic } from "@/lib/haptics";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import {
  Priority,
  type Project,
  type TodoCreate,
} from "../../types/todo-types";
import {
  type InferenceChip,
  priorityChipColor,
  TodoCreateInferences,
} from "./todo-create-inferences";
import { TodoCreateInput } from "./todo-create-input";
import { TodoCreatePickers } from "./todo-create-pickers";

export interface TodoCreateSheetRef {
  open: () => void;
  close: () => void;
}

interface TodoCreateSheetProps {
  projects: Project[];
  defaultProjectId?: string;
  onCreated: (data: TodoCreate) => Promise<void> | void;
}

interface ManualSelections {
  priority?: Priority;
  projectId?: string;
  labels?: string[];
  dueDate?: Date | null;
}

function deviceTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
}

function formatDateChip(d: Date): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(d);
  target.setHours(0, 0, 0, 0);
  const diff = (target.getTime() - today.getTime()) / 86_400_000;
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export const TodoCreateSheet = forwardRef<
  TodoCreateSheetRef,
  TodoCreateSheetProps
>(({ projects, defaultProjectId, onCreated }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [text, setText] = useState("");
  const [manual, setManual] = useState<ManualSelections>({});
  const [submitting, setSubmitting] = useState(false);

  const reset = useCallback(() => {
    setText("");
    setManual({});
  }, []);

  useImperativeHandle(ref, () => ({
    open: () => {
      reset();
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  // Reset when sheet closes so the next open is clean.
  useEffect(() => {
    if (!isOpen) reset();
  }, [isOpen, reset]);

  // Live parse on every keystroke. Manual selections always win over
  // inferred ones — once a user explicitly picks a date/priority/etc.,
  // re-typing should not overwrite that choice.
  const parsed = useMemo(
    () =>
      parseQuickAdd(text, {
        projects: projects.map((p) => ({ id: p.id, name: p.name })),
        timezone: deviceTimezone(),
      }),
    [text, projects],
  );

  const effectiveDueDate = manual.dueDate ?? parsed.dueDate ?? null;
  const effectivePriority = manual.priority ?? parsed.priority ?? Priority.NONE;
  const effectiveProjectId =
    manual.projectId ?? parsed.project?.id ?? defaultProjectId;
  const effectiveLabels =
    manual.labels !== undefined ? manual.labels : parsed.labels;

  const chips: InferenceChip[] = useMemo(() => {
    const out: InferenceChip[] = [];
    if (effectiveDueDate) {
      out.push({
        key: "date",
        kind: "date",
        label: formatDateChip(effectiveDueDate),
        color: "#00bbff",
      });
    }
    if (effectivePriority !== Priority.NONE) {
      out.push({
        key: `priority:${effectivePriority}`,
        kind: "priority",
        label: effectivePriority.toUpperCase(),
        color: priorityChipColor(effectivePriority),
      });
    }
    if (effectiveProjectId) {
      const proj = projects.find((p) => p.id === effectiveProjectId);
      if (proj) {
        out.push({
          key: `project:${proj.id}`,
          kind: "project",
          label: proj.name,
          color: proj.color ?? "#a1a1aa",
        });
      }
    }
    for (const lbl of effectiveLabels) {
      out.push({
        key: `label:${lbl}`,
        kind: "label",
        label: `#${lbl}`,
        color: "#a78bfa",
      });
    }
    return out;
  }, [
    effectiveDueDate,
    effectivePriority,
    effectiveProjectId,
    effectiveLabels,
    projects,
  ]);

  const handleRemoveChip = useCallback(
    (chip: InferenceChip) => {
      // For inferred values, strip the matched substring from the text.
      // For manually picked values, just clear the manual entry.
      switch (chip.kind) {
        case "date": {
          if (manual.dueDate !== undefined) {
            setManual((m) => ({ ...m, dueDate: null }));
            return;
          }
          // Inferred — clear by removing date tokens from text.
          setText((t) =>
            t
              .replace(
                /\b(today|tomorrow|yesterday|in\s+\d+\s+days?|next\s+week|this\s+weekend|next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b/gi,
                " ",
              )
              .replace(/\s+/g, " ")
              .trim(),
          );
          return;
        }
        case "priority": {
          if (manual.priority !== undefined) {
            setManual((m) => ({ ...m, priority: Priority.NONE }));
            return;
          }
          setText((t) =>
            t
              .replace(/\bp[123]\b/gi, " ")
              .replace(/\b(high|urgent|important|medium|normal|low)\b/gi, " ")
              .replace(/\s+/g, " ")
              .trim(),
          );
          return;
        }
        case "project": {
          if (manual.projectId !== undefined) {
            setManual((m) => ({ ...m, projectId: undefined }));
            return;
          }
          setText((t) =>
            t
              .replace(/@[a-zA-Z0-9_-]+\s/g, " ")
              .replace(/\s+/g, " ")
              .trim(),
          );
          return;
        }
        case "label": {
          const lblName = chip.label.replace(/^#/, "");
          if (manual.labels !== undefined) {
            setManual((m) => ({
              ...m,
              labels: (m.labels ?? []).filter((l) => l !== lblName),
            }));
            return;
          }
          setText((t) =>
            t
              .replace(new RegExp(`#${lblName}\\s`, "g"), " ")
              .replace(/\s+/g, " ")
              .trim(),
          );
          return;
        }
      }
    },
    [manual],
  );

  const cleanedTitle = useMemo(() => {
    const raw = parsed.cleanedText.trim();
    return raw || text.trim();
  }, [parsed.cleanedText, text]);

  const canSubmit = cleanedTitle.length > 0 && !submitting;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    const payload: TodoCreate = {
      title: cleanedTitle,
      priority: effectivePriority,
      labels: effectiveLabels,
      ...(effectiveDueDate
        ? {
            due_date: effectiveDueDate.toISOString(),
            due_date_timezone: deviceTimezone(),
          }
        : {}),
      ...(effectiveProjectId ? { project_id: effectiveProjectId } : {}),
    };
    setSubmitting(true);
    notificationHaptic("success");
    try {
      await onCreated(payload);
      reset();
    } finally {
      setSubmitting(false);
    }
  }, [
    canSubmit,
    cleanedTitle,
    effectivePriority,
    effectiveLabels,
    effectiveDueDate,
    effectiveProjectId,
    onCreated,
    reset,
  ]);

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["50%", "90%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#18181b" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <View style={{ flex: 1 }}>
            <TodoCreateInferences chips={chips} onRemove={handleRemoveChip} />
            <TodoCreateInput
              value={text}
              canSubmit={canSubmit}
              onChangeText={setText}
              onSubmit={() => void handleSubmit()}
            />
            <TodoCreatePickers
              dueDate={effectiveDueDate}
              priority={effectivePriority}
              projectId={effectiveProjectId}
              labels={effectiveLabels}
              projects={projects}
              onChangeDueDate={(d) => setManual((m) => ({ ...m, dueDate: d }))}
              onChangePriority={(p) =>
                setManual((m) => ({ ...m, priority: p }))
              }
              onChangeProjectId={(id) =>
                setManual((m) => ({ ...m, projectId: id }))
              }
              onChangeLabels={(labels) => setManual((m) => ({ ...m, labels }))}
            />
          </View>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

TodoCreateSheet.displayName = "TodoCreateSheet";
