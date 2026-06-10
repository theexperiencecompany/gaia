import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  Calendar03Icon,
  Cancel01Icon,
  Delete02Icon,
  Flag02Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import { Priority, type Project } from "../../types/todo-types";

interface TodoBulkActionBarProps {
  selectedCount: number;
  onCancel: () => void;
  onSelectAll: () => void;
  onComplete: () => void;
  onChangePriority: (priority: Priority) => void;
  onMoveToProject: (projectId: string | null) => void;
  onDelete: () => void;
  /** Open the snooze sheet for the current selection. */
  onSnooze: () => void;
  projects: Project[];
}

const PRIORITY_OPTIONS: {
  key: Priority;
  label: string;
  color: string;
}[] = [
  { key: Priority.HIGH, label: "High", color: "#f87171" },
  { key: Priority.MEDIUM, label: "Medium", color: "#facc15" },
  { key: Priority.LOW, label: "Low", color: "#60a5fa" },
  { key: Priority.NONE, label: "None", color: "#a1a1aa" },
];

type SubPanel = "priority" | "project" | null;

/**
 * Header morph + bottom action toolbar shown while in multi-select mode.
 * The header replaces the BackButton/title row with
 * `Cancel · n selected · [Calendar Flag Trash]`.
 *
 * The bottom toolbar reveals expandable sub-panels for "Priority" and
 * "Project" tweaks; "Done" and "Delete" act immediately.
 */
export function TodoBulkActionBar({
  selectedCount,
  onCancel,
  onSelectAll,
  onComplete,
  onChangePriority,
  onMoveToProject,
  onDelete,
  onSnooze,
  projects,
}: TodoBulkActionBarProps) {
  const insets = useSafeAreaInsets();
  const [panel, setPanel] = useState<SubPanel>(null);

  const togglePanel = useCallback((next: SubPanel) => {
    selectionHaptic();
    setPanel((prev) => (prev === next ? null : next));
  }, []);

  return (
    <View
      style={{
        position: "absolute",
        bottom: insets.bottom + 12,
        left: 16,
        right: 16,
        backgroundColor: "rgba(39,39,42,0.92)",
        borderRadius: 20,
        overflow: "hidden",
      }}
    >
      {panel === "priority" && (
        <View
          style={{
            paddingHorizontal: 14,
            paddingVertical: 12,
            borderBottomWidth: 1,
            borderBottomColor: "rgba(63,63,70,0.4)",
            gap: 8,
          }}
        >
          <Text
            style={{
              fontSize: 11,
              color: "#71717a",
              fontWeight: "600",
              letterSpacing: 0.7,
              textTransform: "uppercase",
            }}
          >
            Set priority
          </Text>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            {PRIORITY_OPTIONS.map((opt) => (
              <Pressable
                key={opt.key}
                onPress={() => {
                  selectionHaptic();
                  onChangePriority(opt.key);
                  setPanel(null);
                }}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  paddingHorizontal: 12,
                  paddingVertical: 8,
                  borderRadius: 12,
                  backgroundColor: "rgba(63,63,70,0.40)",
                }}
              >
                <View
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 3,
                    backgroundColor: opt.color,
                  }}
                />
                <Text style={{ fontSize: 13, color: "#e4e4e7" }}>
                  {opt.label}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>
      )}

      {panel === "project" && (
        <View
          style={{
            paddingHorizontal: 14,
            paddingVertical: 12,
            borderBottomWidth: 1,
            borderBottomColor: "rgba(63,63,70,0.4)",
            gap: 8,
          }}
        >
          <Text
            style={{
              fontSize: 11,
              color: "#71717a",
              fontWeight: "600",
              letterSpacing: 0.7,
              textTransform: "uppercase",
            }}
          >
            Move to project
          </Text>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            <Pressable
              onPress={() => {
                selectionHaptic();
                onMoveToProject(null);
                setPanel(null);
              }}
              style={{
                paddingHorizontal: 12,
                paddingVertical: 8,
                borderRadius: 12,
                backgroundColor: "rgba(63,63,70,0.40)",
              }}
            >
              <Text style={{ fontSize: 13, color: "#e4e4e7" }}>No project</Text>
            </Pressable>
            {projects.map((p) => (
              <Pressable
                key={p.id}
                onPress={() => {
                  selectionHaptic();
                  onMoveToProject(p.id);
                  setPanel(null);
                }}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  paddingHorizontal: 12,
                  paddingVertical: 8,
                  borderRadius: 12,
                  backgroundColor: "rgba(63,63,70,0.40)",
                }}
              >
                <View
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    backgroundColor: p.color ?? "#71717a",
                  }}
                />
                <Text style={{ fontSize: 13, color: "#e4e4e7" }}>{p.name}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      )}

      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: 12,
          paddingVertical: 12,
        }}
      >
        <Pressable
          onPress={() => {
            selectionHaptic();
            onCancel();
          }}
          hitSlop={6}
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(63,63,70,0.40)",
          }}
          accessibilityLabel="Cancel selection"
        >
          <AppIcon icon={Cancel01Icon} size={16} color="#e4e4e7" />
        </Pressable>

        <Pressable onPress={onSelectAll} hitSlop={6} style={{ flex: 1 }}>
          <Text
            style={{ fontSize: 13, color: "#a1a1aa", textAlign: "center" }}
          >{`${selectedCount} selected · Select all`}</Text>
        </Pressable>

        <Pressable
          onPress={onSnooze}
          hitSlop={6}
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(63,63,70,0.40)",
          }}
          accessibilityLabel="Snooze selected"
        >
          <AppIcon icon={Calendar03Icon} size={16} color="#e4e4e7" />
        </Pressable>

        <Pressable
          onPress={() => togglePanel("priority")}
          hitSlop={6}
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor:
              panel === "priority"
                ? "rgba(0,187,255,0.18)"
                : "rgba(63,63,70,0.40)",
          }}
          accessibilityLabel="Change priority"
        >
          <AppIcon
            icon={Flag02Icon}
            size={16}
            color={panel === "priority" ? "#00bbff" : "#e4e4e7"}
          />
        </Pressable>

        <Pressable
          onPress={onComplete}
          hitSlop={6}
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(0,187,255,0.18)",
          }}
          accessibilityLabel="Complete selected"
        >
          <AppIcon icon={Tick02Icon} size={16} color="#00bbff" />
        </Pressable>

        <Pressable
          onPress={onDelete}
          hitSlop={6}
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(239,68,68,0.18)",
          }}
          accessibilityLabel="Delete selected"
        >
          <AppIcon icon={Delete02Icon} size={16} color="#ef4444" />
        </Pressable>
      </View>
    </View>
  );
}
