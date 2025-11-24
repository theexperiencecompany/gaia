"use client";

import { Tooltip } from "@heroui/react";
import { usePathname } from "next/navigation";
import { type ReactNode, Suspense, useMemo } from "react";

import { Button } from "@/components";
import SuspenseLoader from "@/components/shared/SuspenseLoader";
import { useHeader } from "@/hooks/layout/useHeader";

import BrowserHeader from "./BrowserHeader";
import CalendarHeader from "./CalendarHeader";
import ChatHeader from "./ChatHeader";
import GoalHeader from "./GoalHeader";
import GoalsHeader from "./GoalsHeader";
import SettingsHeader from "./SettingsHeader";
import TodosHeader from "./TodosHeader";

// Consistent button component for sidebar header buttons
export const SidebarHeaderButton = ({
  children,
  onClick,
  tooltip,
  "aria-label": ariaLabel,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  tooltip?: ReactNode;
  "aria-label": string;
}) => {
  const button = (
    <Button
      aria-label={ariaLabel}
      size="icon"
      variant="ghost"
      className={`group/btn group rounded-xl p-1! hover:bg-[#00bbff]/20 hover:text-primary`}
      onClick={onClick}
    >
      {children}
    </Button>
  );

  if (!tooltip) return button;

  return <Tooltip content={tooltip}>{button}</Tooltip>;
};

export default function HeaderManager() {
  const pathname = usePathname();
  const { header } = useHeader();

  const defaultHeader = useMemo(() => {
    if (pathname.startsWith("/calendar")) return <CalendarHeader />;
    if (pathname.startsWith("/c")) return <ChatHeader />;
    if (pathname.startsWith("/browser")) return <BrowserHeader />;
    if (pathname.startsWith("/todos"))
      return (
        <Suspense fallback={<SuspenseLoader />}>
          <TodosHeader />
        </Suspense>
      );
    if (pathname.match(/^\/goals\/[^/]+$/)) return <GoalHeader />;
    if (pathname.startsWith("/goals")) return <GoalsHeader />;
    if (pathname.startsWith("/settings")) return <SettingsHeader />;
    return null;
  }, [pathname]);

  return <>{header || defaultHeader}</>;
}
