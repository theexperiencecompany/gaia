"use client";

import { Suspense, useMemo } from "react";
import SuspenseLoader from "@/components/shared/SuspenseLoader";
import { useHeader } from "@/hooks/layout/useHeader";
import { usePathname } from "@/i18n/navigation";

import CalendarHeader from "./CalendarHeader";
import ChatHeader from "./ChatHeader";
import GoalHeader from "./GoalHeader";
import GoalsHeader from "./GoalsHeader";
import SettingsHeader from "./SettingsHeader";
import TodosHeader from "./TodosHeader";

export { SidebarHeaderButton } from "./SidebarHeaderButton";

export default function HeaderManager() {
  const pathname = usePathname();
  const { header } = useHeader();

  const defaultHeader = useMemo(() => {
    if (pathname.startsWith("/calendar")) return <CalendarHeader />;
    if (pathname.startsWith("/c")) return <ChatHeader />;
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

  // Memoize the final header to prevent unnecessary re-renders
  const finalHeader = useMemo(
    () => header || defaultHeader,
    [header, defaultHeader],
  );

  return <>{finalHeader}</>;
}
