import { type DueChipTone, getDueChipTone } from "@gaia/shared/utils";
import { View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  RepeatIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { Project, Todo } from "../../types/todo-types";

interface TodoRowMetaProps {
  todo: Todo;
  project: Project | undefined;
}

interface ToneStyle {
  bg: string;
  fg: string;
}

/**
 * Map the shared `DueChipTone` enum onto NativeWind-friendly hex values.
 *
 * Spec §C.11 — "Date chip semantic colours":
 * - completed → bg-zinc-800/40 text-zinc-500
 * - overdue   → bg-red-500/15 text-red-300
 * - today     → bg-[#00bbff]/15 text-[#00bbff]
 * - tomorrow  → bg-zinc-800/60 text-zinc-200
 * - soon      → bg-yellow-500/15 text-yellow-300
 * - later     → bg-zinc-800/60 text-zinc-400
 */
const DUE_TONE_STYLE: Record<DueChipTone, ToneStyle> = {
  completed: { bg: "rgba(39,39,42,0.40)", fg: "#71717a" },
  overdue: { bg: "rgba(239,68,68,0.15)", fg: "#fca5a5" },
  today: { bg: "rgba(0,187,255,0.15)", fg: "#00bbff" },
  tomorrow: { bg: "rgba(39,39,42,0.60)", fg: "#e4e4e7" },
  soon: { bg: "rgba(234,179,8,0.15)", fg: "#fde68a" },
  later: { bg: "rgba(39,39,42,0.60)", fg: "#a1a1aa" },
};

const NEUTRAL_CHIP: ToneStyle = {
  bg: "rgba(39,39,42,0.60)",
  fg: "#a1a1aa",
};

function formatDueLabel(dateStr: string, tone: DueChipTone): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "";
  if (tone === "today") return "Today";
  if (tone === "tomorrow") return "Tomorrow";
  if (tone === "overdue") {
    const now = new Date();
    const startOfNow = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
    ).getTime();
    const startOfDue = new Date(
      d.getFullYear(),
      d.getMonth(),
      d.getDate(),
    ).getTime();
    const days = Math.round((startOfNow - startOfDue) / 86_400_000);
    return `${days}d overdue`;
  }
  if (tone === "soon") {
    return d.toLocaleDateString(undefined, { weekday: "short" });
  }
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const MAX_LABEL_CHIPS = 2;

export function TodoRowMeta({ todo, project }: TodoRowMetaProps) {
  const totalSubtasks = todo.subtasks?.length ?? 0;
  const completedSubtasks =
    todo.subtasks?.filter((s) => s.completed).length ?? 0;

  const visibleLabels = todo.labels.slice(0, MAX_LABEL_CHIPS);
  const overflowLabels = Math.max(0, todo.labels.length - MAX_LABEL_CHIPS);

  const dueTone = getDueChipTone(todo.due_date, todo.completed);
  const dueStyle = DUE_TONE_STYLE[dueTone];

  const hasAny =
    !!todo.due_date ||
    !!todo.recurrence ||
    !!project ||
    visibleLabels.length > 0 ||
    overflowLabels > 0 ||
    totalSubtasks > 0;

  if (!hasAny) return null;

  return (
    <View
      style={{
        flexDirection: "row",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 6,
        marginTop: 4,
      }}
    >
      {!!todo.due_date && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: dueStyle.bg,
            borderRadius: 999,
            paddingHorizontal: 8,
            paddingVertical: 2,
            gap: 4,
          }}
        >
          <AppIcon icon={Calendar03Icon} size={11} color={dueStyle.fg} />
          <Text
            style={{
              fontSize: 11,
              color: dueStyle.fg,
              fontWeight: "500",
            }}
          >
            {formatDueLabel(todo.due_date, dueTone)}
          </Text>
        </View>
      )}

      {!!todo.recurrence && (
        <AppIcon icon={RepeatIcon} size={11} color="#a1a1aa" />
      )}

      {!!project && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: "rgba(39,39,42,0.60)",
            borderRadius: 999,
            paddingHorizontal: 8,
            paddingVertical: 2,
            gap: 5,
          }}
        >
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: project.color ?? "#71717a",
            }}
          />
          <Text style={{ fontSize: 11, color: "#d4d4d8", fontWeight: "500" }}>
            {project.name}
          </Text>
        </View>
      )}

      {visibleLabels.map((label) => (
        <View
          key={label}
          style={{
            backgroundColor: NEUTRAL_CHIP.bg,
            borderRadius: 999,
            paddingHorizontal: 8,
            paddingVertical: 2,
          }}
        >
          <Text
            style={{ fontSize: 11, color: NEUTRAL_CHIP.fg, fontWeight: "500" }}
          >
            {`#${label}`}
          </Text>
        </View>
      ))}

      {overflowLabels > 0 && (
        <View
          style={{
            backgroundColor: NEUTRAL_CHIP.bg,
            borderRadius: 999,
            paddingHorizontal: 8,
            paddingVertical: 2,
          }}
        >
          <Text
            style={{ fontSize: 11, color: NEUTRAL_CHIP.fg, fontWeight: "500" }}
          >{`+${overflowLabels}`}</Text>
        </View>
      )}

      {totalSubtasks > 0 && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 3,
          }}
        >
          <AppIcon icon={CheckmarkCircle02Icon} size={11} color="#71717a" />
          <Text style={{ fontSize: 11, color: "#71717a", fontWeight: "500" }}>
            {`${completedSubtasks}/${totalSubtasks}`}
          </Text>
        </View>
      )}
    </View>
  );
}
