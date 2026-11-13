"use client";

import type { EventProperties } from "@gaia/shared/analytics/events";
import {
  Calendar01Icon,
  CalendarUpload02Icon,
  Flag02Icon,
  Folder02Icon,
  InboxCheckIcon,
  InboxIcon,
  PlusSignIcon,
  Tag01Icon,
} from "@icons";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import Spinner from "@/components/ui/spinner";
import AddProjectModal from "@/features/todo/components/AddProjectModal";
import TodoModal from "@/features/todo/components/TodoModal";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { priorityTextColors } from "@/features/todo/utils/priorityColors";
import { usePathname } from "@/i18n/navigation";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { Priority } from "@/types/features/todoTypes";
import { accordionItemStyles } from "../constants";

const HighPriorityIcon = () => (
  <Flag02Icon
    width={18}
    height={18}
    style={{ color: priorityTextColors[Priority.HIGH] }}
  />
);

const MediumPriorityIcon = () => (
  <Flag02Icon
    width={18}
    height={18}
    style={{ color: priorityTextColors[Priority.MEDIUM] }}
  />
);

const LowPriorityIcon = () => (
  <Flag02Icon
    width={18}
    height={18}
    style={{ color: priorityTextColors[Priority.LOW] }}
  />
);

const LabelTagIcon = () => <Tag01Icon width={18} height={18} />;

function ProjectIcon({ color }: { color?: string }) {
  return (
    <div className="flex items-center">
      <Folder02Icon className="w-[20px]" style={{ color }} />
    </div>
  );
}

const PRIORITY_MENU_ITEMS = [
  {
    label: "High Priority",
    icon: HighPriorityIcon,
    href: "/todos/priority/high",
    view: "priority_high",
  },
  {
    label: "Medium Priority",
    icon: MediumPriorityIcon,
    href: "/todos/priority/medium",
    view: "priority_medium",
  },
  {
    label: "Low Priority",
    icon: LowPriorityIcon,
    href: "/todos/priority/low",
    view: "priority_low",
  },
] satisfies MenuItem[];

type TodoView = EventProperties["todos:view_changed"]["view_kind"];

type MenuItem = {
  label: string;
  icon: React.ComponentType<{ className?: string; color?: string }>;
  iconColor?: string;
  href: string;
  view: TodoView;
  count?: number;
};

type SidebarSectionProps = {
  title?: string;
  items: MenuItem[];
  activeItem: string;
  onItemClick: (item: MenuItem) => void;
  action?: React.ReactNode;
  emptyState?: {
    loading: boolean;
    message: string;
  };
};

function SidebarSection({
  title,
  items,
  activeItem,
  onItemClick,
  action,
  emptyState,
}: SidebarSectionProps) {
  return (
    <div className="pb-1">
      {title && (
        <div className="mb-1 flex items-center justify-between">
          <span className={cn(accordionItemStyles.trigger)}>{title}</span>
          {action}
        </div>
      )}
      {items.length > 0 ? (
        items.map((item) => (
          <GaiaButton
            key={item.href}
            fullWidth
            className="justify-start text-start text-sm"
            variant={activeItem === item.href ? "tertiary" : "ghost"}
            tone={activeItem === item.href ? "dim" : "faint"}
            hoverTone={activeItem === item.href ? "none" : "dim"}
            inset="tight"
            size="sm"
            onPress={() => onItemClick(item)}
          >
            <item.icon className="w-[20px]" color={item.iconColor} />
            {item.label}
            {item.count !== undefined && (
              <span className="ml-auto text-xs">{item.count}</span>
            )}
          </GaiaButton>
        ))
      ) : emptyState ? (
        emptyState.loading ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : (
          <div className="text-center text-xs text-zinc-500 italic">
            {emptyState.message}
          </div>
        )
      ) : null}
    </div>
  );
}

export default function TodoSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [addProjectOpen, setAddProjectOpen] = useState(false);
  // const [searchQuery, setSearchQuery] = useState("");

  // Track initial load to prevent showing spinner on navigation
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  const {
    projects,
    labels,
    counts,
    loading,
    loadProjects,
    loadLabels,
    loadCounts,
    // refreshAllData,
  } = useTodoData({ autoLoad: false });

  // Load initial data on mount
  useEffect(() => {
    let cancelled = false;
    const loadData = async () => {
      await Promise.all([loadProjects(), loadCounts(), loadLabels()]);
      if (!cancelled) setIsInitialLoad(false);
    };

    loadData();
    return () => {
      cancelled = true;
    };
  }, [loadProjects, loadCounts, loadLabels]);

  const handleNavigation = (item: MenuItem) => {
    track("todos:view_changed", { view_kind: item.view });
    router.push(item.href);
  };

  const mainMenuItems: MenuItem[] = useMemo(
    () => [
      {
        label: "Inbox",
        icon: InboxIcon,
        href: "/todos",
        view: "inbox",
        count: counts.inbox,
      },
      {
        label: "Today",
        icon: Calendar01Icon,
        href: "/todos/today",
        view: "today",
        count: counts.today,
      },
      {
        label: "Upcoming",
        icon: CalendarUpload02Icon,
        href: "/todos/upcoming",
        view: "upcoming",
        count: counts.upcoming,
      },
      {
        label: "Completed",
        icon: InboxCheckIcon,
        href: "/todos/completed",
        view: "completed",
        count: counts.completed,
      },
    ],
    [counts.inbox, counts.today, counts.upcoming, counts.completed],
  );

  // Label items - show top 5 most used labels or empty state
  const labelMenuItems: MenuItem[] = useMemo(
    () =>
      labels.length > 0
        ? labels.slice(0, 5).map((label) => ({
            label: label.name,
            icon: LabelTagIcon,
            href: `/todos/label/${encodeURIComponent(label.name)}`,
            view: "label",
            count: label.count,
          }))
        : [],
    [labels],
  );

  // Project items - convert projects to menu items or empty state (one pass)
  const projectMenuItems: MenuItem[] = useMemo(() => {
    const items: MenuItem[] = [];
    for (const project of projects) {
      if (project.is_default) continue;
      items.push({
        label: project.name,
        icon: ProjectIcon,
        iconColor: project.color,
        href: `/todos/project/${project.id}`,
        view: "project",
        count: project.todo_count,
      });
    }
    return items;
  }, [projects]);

  return (
    <>
      <div className="flex flex-col space-y-3">
        <TodoModal mode="add" />

        {/* TODO: fix implementation on backend then integrate. */}
        {/* <form onSubmit={handleSearch} className="mb-4">
          <Input
            placeholder="search tasks..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            startContent={
              <SearchIcon className="h-4 w-4 text-zinc-500" />
            }
            size="sm"
            radius="sm"
            classNames={{
              input: "text-xs",
              inputWrapper: "h-8",
            }}
          />
        </form> */}

        {isInitialLoad && loading ? (
          <div className="flex h-[400px] w-full items-center justify-center">
            <Spinner />
          </div>
        ) : (
          <div className="space-y-2">
            {/* Main Menu */}
            <SidebarSection
              items={mainMenuItems}
              activeItem={pathname}
              onItemClick={handleNavigation}
            />

            {/* Priorities */}
            <SidebarSection
              title="Priorities"
              items={PRIORITY_MENU_ITEMS}
              activeItem={pathname}
              onItemClick={handleNavigation}
            />

            {/* Labels */}
            <SidebarSection
              title="Labels"
              items={labelMenuItems}
              activeItem={pathname}
              onItemClick={handleNavigation}
              emptyState={{
                loading: isInitialLoad && loading,
                message: "No labels yet",
              }}
            />

            {/* Projects */}
            <SidebarSection
              title="Projects"
              items={projectMenuItems}
              activeItem={pathname}
              onItemClick={handleNavigation}
              action={
                <GaiaButton
                  aria-label="Add project"
                  isIconOnly
                  size="sm"
                  variant="ghost"
                  onPress={() => setAddProjectOpen(true)}
                  className="h-6 w-6 min-w-6"
                >
                  <PlusSignIcon className="h-3 w-3" />
                </GaiaButton>
              }
              emptyState={{
                loading: isInitialLoad && loading,
                message: "No projects yet",
              }}
            />
          </div>
        )}
      </div>

      <AddProjectModal
        open={addProjectOpen}
        onOpenChange={setAddProjectOpen}
        onSuccess={() => {
          loadCounts();
          loadProjects();
        }}
      />
    </>
  );
}
