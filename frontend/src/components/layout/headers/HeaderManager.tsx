"use client";

import { Tooltip } from "@heroui/react";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";

import { Button } from "@/components";
import { useHeader } from "@/hooks/layout/useHeader";

import BrowserHeader from "./BrowserHeader";
import ChatHeader from "./ChatHeader";
import SettingsHeader from "./SettingsHeader";

function getDefaultHeaderForPath(pathname: string) {
  if (pathname.startsWith("/c")) return <ChatHeader />;
  if (pathname.startsWith("/browser")) return <BrowserHeader />;
  if (pathname.startsWith("/settings")) return <SettingsHeader />;
  return null;
}

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

  // If a custom header is set, use it. Otherwise, use route-based default.
  const displayHeader = header || getDefaultHeaderForPath(pathname);

  return <>{displayHeader}</>;
}
