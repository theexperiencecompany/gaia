"use client";

import { Button } from "@heroui/button";
import { CancelIcon, ZapIcon } from "@icons";
import { useEffect, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";

const STORAGE_KEY = "sidebar-promo-collapsed:v1";

interface SidebarPromoProps {
  price: number;
  onUpgrade: () => void;
}

export function SidebarPromo({ price, onUpgrade }: SidebarPromoProps) {
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
            <div className="font-medium text-sm">You Deserve This!</div>
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
          <p className="text-xs text-zinc-400">
            Unlock near-unlimited usage and priority support for ${price} a
            month
          </p>
        </>
      )}

      <RaisedButton
        className={`w-full rounded-xl! text-black! ${isCollapsed ? "" : "mt-2"}`}
        color="#00bbff"
        size={"sm"}
        onClick={onUpgrade}
      >
        <ZapIcon fill="black" width={17} height={17} />
        Upgrade to Pro
      </RaisedButton>
    </div>
  );
}
