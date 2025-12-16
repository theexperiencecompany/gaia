"use client";

import { Button } from "@heroui/button";
import { useDisclosure } from "@heroui/modal";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Spinner from "@/components/ui/spinner";
import AddProjectModal from "@/features/todo/components/AddProjectModal";
import { priorityTextColors } from "@/features/todo/components/TodoItem";
import TodoModal from "@/features/todo/components/TodoModal";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import {
  Calendar01Icon,
  CalendarUpload02Icon,
  Flag02Icon,
  Folder02Icon,
  InboxCheckIcon,
  InboxIcon,
  PlusSignIcon,
  Tag01Icon,
} from "@/icons";
import { cn } from "@/lib";
import { Priority } from "@/types/features/todoTypes";
import { accordionItemStyles } from "../constants";

type MenuItem = {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  href: string;
  count?: number;
};

type SidebarSectionProps = {
  title?: string;
  items: MenuItem[];
  activeItem: string;
  onItemClick: (href: string) => void;
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
          <Button
            key={item.href}
            fullWidth
            startContent={<item.icon className="w-[20px]" />}
            endContent={
              item.count !== undefined && (
                <span className="ml-auto text-xs">{item.count}</span>
              )
            }
            className={`justify-start px-2 text-start text-sm ${
              activeItem === item.href
                ? "bg-zinc-800 text-zinc-300"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
            variant="light"
            radius="sm"
            size="sm"
            onPress={() => onItemClick(item.href)}
          >
            {item.label}
          </Button>
        ))
      ) : emptyState ? (
        emptyState.loading ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : (
          <div className="text-center text-xs text-foreground-400 italic">
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
  const {
    isOpen: addProjectOpen,
    onOpen: openAddProject,
    onOpenChange: setAddProjectOpen,
  } = useDisclosure();
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
    const loadData = async () => {
      await Promise.all([loadProjects(), loadCounts(), loadLabels()]);
      setIsInitialLoad(false);
    };

    loadData();
  }, [loadProjects, loadCounts, loadLabels]);

  const handleNavigation = (href: string) => {
    router.push(href);
  };

  // const handleSearch = (e: React.FormEvent) => {
  //   e.preventDefault();
  //   if (searchQuery.trim()) {
  //     router.push(`/todos/search?q=${encodeURIComponent(searchQuery)}`);
  //   }
  // };

  const mainMenuItems: MenuItem[] = [
    {
      label: "Inbox",
      icon: InboxIcon,
      href: "/todos",
      count: counts.inbox,
    },
    {
      label: "Today",
      icon: Calendar01Icon,
      href: "/todos/today",
      count: counts.today,
    },
    {
      label: "Upcoming",
      icon: CalendarUpload02Icon,
      href: "/todos/upcoming",
      count: counts.upcoming,
    },
    {
      label: "Completed",
      icon: InboxCheckIcon,
      href: "/todos/completed",
      count: counts.completed,
    },
  ];

  // Priority items
  const priorityMenuItems: MenuItem[] = [
    {
      label: "High Priority",
      icon: () => (
        <Flag02Icon
          width={18}
          height={18}
          style={{ color: priorityTextColors[Priority.HIGH] }}
        />
      ),
      href: "/todos/priority/high",
    },
    {
      label: "Medium Priority",
      icon: () => (
        <Flag02Icon
          width={18}
          height={18}
          style={{ color: priorityTextColors[Priority.MEDIUM] }}
        />
      ),
      href: "/todos/priority/medium",
    },
    {
      label: "Low Priority",
      icon: () => (
        <Flag02Icon
          width={18}
          height={18}
          style={{ color: priorityTextColors[Priority.LOW] }}
        />
      ),
      href: "/todos/priority/low",
    },
  ];

  // Label items - show top 5 most used labels or empty state
  const labelMenuItems: MenuItem[] =
    labels.length > 0
      ? labels.slice(0, 5).map((label) => ({
          label: label.name,
          icon: () => <Tag01Icon width={18} height={18} />,
          href: `/todos/label/${encodeURIComponent(label.name)}`,
          count: label.count,
        }))
      : [];

  // Project color component
  const ProjectIcon = ({ color }: { color?: string }) => {
    return (
      <div className="flex items-center">
        <Folder02Icon className="w-[20px]" style={{ color }} />
      </div>
    );
  };

  // Project items - convert projects to menu items or empty state
  const projectMenuItems: MenuItem[] = projects
    .filter((p) => !p.is_default)
    .map((project) => ({
      label: project.name,
      icon: () => <ProjectIcon color={project.color} />,
      href: `/todos/project/${project.id}`,
      count: project.todo_count,
    }));

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
              <SearchIcon className="h-4 w-4 text-foreground-400" />
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
              items={priorityMenuItems}
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
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  onPress={openAddProject}
                  className="h-6 w-6 min-w-6"
                >
                  <PlusSignIcon className="h-3 w-3" />
                </Button>
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
