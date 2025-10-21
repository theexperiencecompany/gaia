"use client";

import { Button } from "@heroui/button";
import Link from "next/link";
import { usePathname } from "next/navigation";

import ChatsList from "@/components/layout/sidebar/ChatsList";
import CalendarSidebar from "@/components/layout/sidebar/variants/CalendarSidebar";
import EmailSidebar from "@/components/layout/sidebar/variants/MailSidebar";
import SettingsSidebar from "@/components/layout/sidebar/variants/SettingsSidebar";
import TodoSidebar from "@/components/layout/sidebar/variants/TodoSidebar";
import { PencilEdit02Icon } from "@/components/shared/icons";

export default function Sidebar() {
  // const [open, setOpen] = useState<boolean>(false);
  const pathname = usePathname();

  // Determine which sidebar to show based on the current route
  if (pathname.startsWith("/todos")) return <TodoSidebar />;
  if (pathname.startsWith("/mail")) return <EmailSidebar />;
  if (pathname.startsWith("/calendar")) return <CalendarSidebar />;
  if (pathname.startsWith("/settings")) return <SettingsSidebar />;

  // Default to chat sidebar
  return (
    <div>
      <div className="flex w-full justify-center">
        <Button
          color="primary"
          size="sm"
          fullWidth
          as={Link}
          href="/c"
          className="mb-4 flex justify-start text-sm font-medium text-primary"
          variant="flat"
        >
          <PencilEdit02Icon color={undefined} width={18} height={18} />
          New Chat
        </Button>
      </div>
      <ChatsList />
      {/* <ComingSoonModal isOpen={open} setOpen={setOpen} /> */}
    </div>
  );
}
