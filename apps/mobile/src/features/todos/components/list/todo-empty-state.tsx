import { View } from "react-native";
import { Add01Icon, AppIcon } from "@/components/icons";
import {
  type AppEmptyStateAction,
  AppEmptyStateCard,
} from "@/shared/components/ui/app-empty-state-card";
import {
  TODO_EMPTY_STATE_COPY,
  TODO_SEARCH_EMPTY_STATE,
  type TodoEmptyStateCopy,
} from "../../constants";
import type { FilterTab } from "../../types/todo-types";

interface TodoEmptyStateProps {
  filter: FilterTab;
  /** When true, renders the "no search matches" copy instead. */
  isSearchEmpty?: boolean;
  onAddTodo?: () => void;
}

function EmptyIcon({ copy }: { copy: TodoEmptyStateCopy }) {
  return (
    <View
      style={{
        width: 64,
        height: 64,
        borderRadius: 32,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "rgba(39,39,42,0.40)",
        marginBottom: 4,
      }}
    >
      <AppIcon icon={copy.icon} size={28} color="#a1a1aa" />
    </View>
  );
}

/**
 * Per-filter empty state. Spec §C.empty/loading/error provides the copy
 * table; we route through `AppEmptyStateCard` so the shape matches every
 * other empty state in the app.
 */
export function TodoEmptyState({
  filter,
  isSearchEmpty = false,
  onAddTodo,
}: TodoEmptyStateProps) {
  const copy = isSearchEmpty
    ? TODO_SEARCH_EMPTY_STATE
    : TODO_EMPTY_STATE_COPY[filter];

  const action: AppEmptyStateAction | undefined =
    copy.showCta && onAddTodo
      ? {
          label: copy.ctaLabel ?? "Add todo",
          onPress: onAddTodo,
          variant: "primary",
          icon: <AppIcon icon={Add01Icon} size={14} color="#0a0a0a" />,
        }
      : undefined;

  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: 24,
        paddingVertical: 64,
      }}
    >
      <AppEmptyStateCard
        title={copy.title}
        description={copy.description}
        icon={<EmptyIcon copy={copy} />}
        action={action}
        className="w-full bg-transparent"
      />
    </View>
  );
}
