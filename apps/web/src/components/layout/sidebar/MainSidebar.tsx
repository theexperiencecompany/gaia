"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

import ChatsList from "@/components/layout/sidebar/ChatsList";
import CalendarSidebar from "@/components/layout/sidebar/variants/CalendarSidebar";
import GoalsSidebar from "@/components/layout/sidebar/variants/GoalsSidebar";
import IntegrationsSidebar from "@/components/layout/sidebar/variants/IntegrationsSidebar";
import EmailSidebar from "@/components/layout/sidebar/variants/MailSidebar";
import SettingsSidebar from "@/components/layout/sidebar/variants/SettingsSidebar";
import TodoSidebar from "@/components/layout/sidebar/variants/TodoSidebar";
import WorkflowsSidebar from "@/components/layout/sidebar/variants/WorkflowsSidebar";
import SuspenseLoader from "@/components/shared/SuspenseLoader";
import { BubbleChatAddIcon } from "@/icons";

export default function Sidebar() {
  const pathname = usePathname();

  // Determine which sidebar to show based on the current route
  if (pathname.startsWith("/todos")) return <TodoSidebar />;
  if (pathname.startsWith("/mail")) return <EmailSidebar />;
  if (pathname.startsWith("/calendar")) return <CalendarSidebar />;
  if (pathname.startsWith("/workflows")) return <WorkflowsSidebar />;
  if (pathname.startsWith("/goals")) return <GoalsSidebar />;
  if (pathname.startsWith("/settings"))
    return (
      <Suspense fallback={<SuspenseLoader />}>
        <SettingsSidebar />
      </Suspense>
    );

  // Dashboard - empty sidebar (no chats list)
  if (pathname.startsWith("/dashboard")) {
    return null;
  }

  // Integrations - show integrations sidebar
  if (pathname.startsWith("/integrations")) {
    return <IntegrationsSidebar />;
  }

  // Chat pages (/c and /c/[id]) - show chat sidebar with ChatsList
  return (
    <div>
      <div className="flex w-full justify-center">
        <Tooltip
          content={
            <span className="flex items-center gap-2">
              New Chat
              <Kbd className="text-[10px]">C</Kbd>
            </span>
          }
          placement="right"
        >
          <Button
            color="primary"
            size="sm"
            fullWidth
            as={Link}
            href="/c"
            className="mb-4 flex justify-start text-sm font-medium text-primary"
            variant="flat"
            data-keyboard-shortcut="create-chat"
          >
            <BubbleChatAddIcon width={18} height={18} />
            New Chat
          </Button>
        </Tooltip>
      </div>
      <ChatsList />
    </div>
  );
}
