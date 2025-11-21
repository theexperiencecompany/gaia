"use client";

import { Button } from "@heroui/button";
import { useDisclosure } from "@heroui/modal";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Spinner from "@/components/ui/shadcn/spinner";
import AddProjectModal from "@/features/todo/components/AddProjectModal";
import TodoModal from "@/features/todo/components/TodoModal";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { Plus, Tag } from "@/icons";
import {
  Appointment01Icon,
  Calendar01Icon,
  Calendar03Icon,
  CalendarCheckOut02Icon,
  Folder02Icon,
  LabelImportantIcon,
} from "@/icons";
import { Priority } from "@/types/features/todoTypes";

type MenuItem = {
  label: string;
  icon: React.ElementType;
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
        <div className="mb-1 flex items-center justify-between px-1">
          <span className="text-xs text-zinc-500">{title}</span>
          {action}
        </div>
      )}
      {items.length > 0 ? (
        items.map((item) => (
          <Button
            key={item.href}
            fullWidth
            startContent={
              <item.icon className="w-[20px] text-foreground-500" />
            }
            endContent={
              item.count !== undefined && (
                <span className="ml-auto text-xs text-foreground-500">
                  {item.count}
                </span>
              )
            }
            className={`justify-start px-2 text-start text-sm ${
              activeItem === item.href
                ? "bg-primary/10 text-primary"
                : "text-zinc-400"
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
          <div className="py-4 text-center text-xs text-foreground-400 italic">
            {emptyState.message}
          </div>
        )
      ) : null}
    </div>
  );
}

// Priority colors mapping
const priorityColors: Record<Priority, string> = {
  [Priority.HIGH]: "#ef4444", // red
  [Priority.MEDIUM]: "#eab308", // yellow
  [Priority.LOW]: "#3b82f6", // blue
  [Priority.NONE]: "#6b7280", // gray
};
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
      icon: Calendar03Icon,
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
      icon: CalendarCheckOut02Icon,
      href: "/todos/upcoming",
      count: counts.upcoming,
    },
    {
      label: "Completed",
      icon: Appointment01Icon,
      href: "/todos/completed",
      count: counts.completed,
    },
  ];

  // Priority items
  const priorityMenuItems: MenuItem[] = [
    {
      label: "High Priority",
      icon: () => (
        <LabelImportantIcon width={19} color={priorityColors[Priority.HIGH]} />
      ),
      href: "/todos/priority/high",
    },
    {
      label: "Medium Priority",
      icon: () => (
        <LabelImportantIcon
          width={19}
          color={priorityColors[Priority.MEDIUM]}
        />
      ),
      href: "/todos/priority/medium",
    },
    {
      label: "Low Priority",
      icon: () => (
        <LabelImportantIcon width={19} color={priorityColors[Priority.LOW]} />
      ),
      href: "/todos/priority/low",
    },
  ];

  // Label items - show top 5 most used labels or empty state
  const labelMenuItems: MenuItem[] =
    labels.length > 0
      ? labels.slice(0, 5).map((label) => ({
          label: label.name,
          icon: () => <Tag className="w-[20px]" strokeWidth={1.5} />,
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
          <div className="space-y-4">
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
                  <Plus className="h-3 w-3" />
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
