"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { CancelIcon } from "@icons";
import { type ReactNode, useEffect, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";

interface SidebarPromoProps {
  heading: string;
  /** Null while the line is still loading (a live price, say) or has nothing to say. */
  body: string | null;
  isBodyLoading: boolean;
  cta: string;
  icon: ReactNode;
  onAction: () => void;
  /** localStorage key remembering that the card was collapsed to its button. */
  collapseKey: string;
  onCollapse?: () => void;
}

/** The sidebar's one promo card: heading, a line, a raised CTA; collapses to the CTA alone. */
export function SidebarPromo({
  heading,
  body,
  isBodyLoading,
  cta,
  icon,
  onAction,
  collapseKey,
  onCollapse,
}: SidebarPromoProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(collapseKey);
      if (stored) setIsCollapsed(JSON.parse(stored));
    } catch {
      // localStorage unavailable (e.g. incognito/Safari) — use default
    }
  }, [collapseKey]);

  const handleCollapse = () => {
    setIsCollapsed(true);
    onCollapse?.();
    try {
      localStorage.setItem(collapseKey, JSON.stringify(true));
    } catch {
      // localStorage unavailable — state still updated in memory
    }
  };

  return (
    <div
      className={`flex flex-col justify-center transition-all duration-200 group/pricingsidebar ${isCollapsed ? "w-full px-1 mb-2 mt-1" : "mb-2 h-fit w-fit rounded-2xl bg-zinc-800 p-4 pt-1"}`}
    >
      {!isCollapsed && (
        <>
          <div className="flex w-full justify-between items-center gap-1">
            <div className="font-medium text-sm">{heading}</div>
            <Button
              isIconOnly
              variant="light"
              size="sm"
              radius="full"
              className="p-0! text-zinc-400 hover:text-white relative left-3 group-hover/pricingsidebar:opacity-100 opacity-0 transition"
              onPress={() => handleCollapse()}
            >
              <CancelIcon width={15} height={15} />
            </Button>
          </div>
          {body !== null ? (
            <p className="text-xs text-zinc-400">{body}</p>
          ) : (
            isBodyLoading && <Skeleton className="mt-1 h-8 w-full rounded-lg" />
          )}
        </>
      )}

      <RaisedButton
        className={`w-full rounded-xl! text-black! ${isCollapsed ? "" : "mt-2"}`}
        color="#00bbff"
        size={"sm"}
        onClick={onAction}
      >
        {icon}
        {cta}
      </RaisedButton>
    </div>
  );
}
