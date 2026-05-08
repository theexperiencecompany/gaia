import type { AnyIcon } from "@/components/icons";
import {
  Calendar01Icon,
  CheckmarkCircle02Icon,
  Search01Icon,
  SunriseIcon,
  TaskDailyIcon,
} from "@/components/icons";
import type { FilterTab } from "../types/todo-types";

export interface TodoEmptyStateCopy {
  icon: AnyIcon;
  title: string;
  description: string;
  showCta: boolean;
  ctaLabel?: string;
}

export const TODO_EMPTY_STATE_COPY: Record<FilterTab, TodoEmptyStateCopy> = {
  today: {
    icon: SunriseIcon,
    title: "Nothing due today",
    description: "Enjoy the calm, or add something to tackle.",
    showCta: true,
    ctaLabel: "Add todo",
  },
  upcoming: {
    icon: Calendar01Icon,
    title: "No upcoming todos",
    description: "You're caught up for the next week.",
    showCta: false,
  },
  inbox: {
    icon: TaskDailyIcon,
    title: "Inbox zero",
    description: "Capture quick thoughts here, sort them later.",
    showCta: true,
    ctaLabel: "Add todo",
  },
  overdue: {
    icon: CheckmarkCircle02Icon,
    title: "No overdue todos",
    description: "You're on top of things.",
    showCta: false,
  },
  completed: {
    icon: CheckmarkCircle02Icon,
    title: "No completed todos yet",
    description: "Finished todos will land here.",
    showCta: false,
  },
  all: {
    icon: TaskDailyIcon,
    title: "No todos yet",
    description: "Capture something you need to remember.",
    showCta: true,
    ctaLabel: "Add todo",
  },
};

export const TODO_SEARCH_EMPTY_STATE: TodoEmptyStateCopy = {
  icon: Search01Icon,
  title: "No matches",
  description: "Try different keywords or clear filters.",
  showCta: false,
};
