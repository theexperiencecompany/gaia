"use client";

import { Kbd, Tooltip } from "@heroui/react";
import { BubbleChatAddIcon } from "@icons";
import { Suspense } from "react";
import ChatsList from "@/components/layout/sidebar/ChatsList";

import IntegrationsSidebar from "@/components/layout/sidebar/variants/IntegrationsSidebar";
import SettingsSidebar from "@/components/layout/sidebar/variants/SettingsSidebar";
import TodoSidebar from "@/components/layout/sidebar/variants/TodoSidebar";
import WorkflowsSidebar from "@/components/layout/sidebar/variants/WorkflowsSidebar";
import { LinkButton } from "@/components/shared/LinkButton";
import SuspenseLoader from "@/components/shared/SuspenseLoader";
import { prepareNewChat } from "@/features/chat/utils/newChatNavigation";
import { usePathname } from "@/i18n/navigation";

export default function Sidebar() {
  const pathname = usePathname();

  // Determine which sidebar to show based on the current route
  if (pathname.startsWith("/todos")) return <TodoSidebar />;
  if (pathname.startsWith("/workflows")) return <WorkflowsSidebar />;
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
        <Tooltip>
          <LinkButton
            href="/c"
            onClick={prepareNewChat}
            size="sm"
            fullWidth
            className="mb-4 flex justify-start text-sm font-medium text-primary"
            variant="tertiary"
            data-keyboard-shortcut="create-chat"
          >
            <BubbleChatAddIcon width={18} height={18} />
            New Chat
          </LinkButton>
          <Tooltip.Content placement="right">
            <span className="flex items-center gap-2">
              New Chat
              <Kbd className="text-[10px]">C</Kbd>
            </span>
          </Tooltip.Content>
        </Tooltip>
      </div>
      <ChatsList />
    </div>
  );
}
