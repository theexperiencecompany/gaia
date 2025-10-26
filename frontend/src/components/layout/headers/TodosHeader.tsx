"use client";

import { Tooltip } from "@heroui/react";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { CheckmarkCircle02Icon } from "@/components/shared/icons";
import { NotificationCenter } from "@/features/notification/components/NotificationCenter";
import TodoModal from "@/features/todo/components/TodoModal";
import { useTodoStore } from "@/stores/todoStore";

export default function TodosHeader() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Get data from store instead of making duplicate API call
  const todos = useTodoStore((state) => state.todos);
  const projects = useTodoStore((state) => state.projects);
  const loadCounts = useTodoStore((state) => state.loadCounts);

  // Get filter parameters
  const projectId = searchParams.get("project");
  const priority = searchParams.get("priority");

  // Determine page title and task count
  const { pageTitle, taskCount } = useMemo(() => {
    let title = "Inbox";
    let count = 0;

    if (pathname === "/todos/today") {
      title = "Today";
    } else if (pathname === "/todos/upcoming") {
      title = "Upcoming";
    } else if (pathname === "/todos/completed") {
      title = "Completed";
      count = todos.length;
    } else if (pathname.startsWith("/todos/priority/")) {
      const priorityValue = priority || pathname.split("/").pop();
      if (priorityValue) {
        title = `${priorityValue.charAt(0).toUpperCase() + priorityValue.slice(1)} Priority`;
      }
    } else if (pathname.startsWith("/todos/label/")) {
      const labelValue = pathname.split("/").pop();
      if (labelValue) {
        title = labelValue.charAt(0).toUpperCase() + labelValue.slice(1);
      }
    } else if (projectId || pathname.startsWith("/todos/project/")) {
      const project = projects.find(
        (p) => p.id === (projectId || pathname.split("/").pop()),
      );
      title = project ? project.name : "Project";
    }

    // Count incomplete todos unless we're on the completed page
    count =
      pathname === "/todos/completed"
        ? todos.length
        : todos.filter((t) => !t.completed).length;

    return { pageTitle: title, taskCount: count };
  }, [pathname, priority, projectId, projects, todos]);

  return (
    <div className="flex w-full items-center justify-between">
      <div className="flex items-center gap-2 pl-2 text-zinc-500">
        <Link href={"/todos"} className="flex items-center gap-2">
          <CheckmarkCircle02Icon width={20} height={20} color={undefined} />
          <span>Todos</span>
        </Link>
        {pageTitle !== "Inbox" && (
          <>
            <ChevronRight width={18} height={17} />
            <span className="text-zinc-300">{pageTitle}</span>
          </>
        )}
        <>
          <ChevronRight width={18} height={17} />
          <span className="text-sm text-zinc-400">
            {taskCount} {taskCount === 1 ? "task" : "tasks"}
          </span>
        </>
      </div>

      <div className="relative z-[100] flex items-center">
        <Tooltip content="Create new todo">
          <div className="group/btn [&_svg]:!h-5 [&_svg]:!w-5 [&_svg]:!text-zinc-400 hover:[&_svg]:!text-primary">
            <TodoModal
              mode="add"
              buttonText=""
              buttonClassName="!p-1.5 !m-0 !bg-transparent !min-w-0 hover:!bg-[#00bbff]/20 data-[hover=true]:!bg-[#00bbff]/20 rounded-xl"
              onSuccess={async () => {
                await loadCounts();
              }}
            />
          </div>
        </Tooltip>
        <NotificationCenter />
      </div>
    </div>
  );
}
