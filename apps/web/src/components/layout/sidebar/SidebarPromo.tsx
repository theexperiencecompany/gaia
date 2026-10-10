"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { CancelIcon, ZapIcon } from "@icons";
import { useEffect, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import type { PaywallCopy } from "@/features/pricing/constants";

const STORAGE_KEY = "sidebar-promo-collapsed:v1";

interface SidebarPromoProps {
  /** The live Pro monthly price; null while loading or when the plans could not be read. */
  price: number | null;
  isPriceLoading: boolean;
  copy: PaywallCopy;
  onUpgrade: () => void;
}

export function SidebarPromo({
  price,
  isPriceLoading,
  copy,
  onUpgrade,
}: SidebarPromoProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setIsCollapsed(JSON.parse(stored));
    } catch {
      // localStorage unavailable (e.g. incognito/Safari) — use default
    }
  }, []);

  const handleCollapse = () => {
    const newState = true;
    setIsCollapsed(newState);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newState));
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
            <div className="font-medium text-sm">{copy.heading}</div>
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
          {price !== null ? (
            <p className="text-xs text-zinc-400">{copy.sidebarBody(price)}</p>
          ) : (
            isPriceLoading && (
              <Skeleton className="mt-1 h-8 w-full rounded-lg" />
            )
          )}
        </>
      )}

      <RaisedButton
        className={`w-full rounded-xl! text-black! ${isCollapsed ? "" : "mt-2"}`}
        color="#00bbff"
        size={"sm"}
        onClick={onUpgrade}
      >
        <ZapIcon fill="black" width={17} height={17} />
        {copy.cta}
      </RaisedButton>
    </div>
  );
}
