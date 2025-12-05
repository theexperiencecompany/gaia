"use client";

import { Button } from "@heroui/button";
import Link from "next/link";
import type React from "react";
import { useEffect, useState } from "react";

import { RaisedButton } from "@/components/ui/raised-button";
import { CancelIcon, ZapIcon } from "@/icons";

const STORAGE_KEY = "sidebar-promo-collapsed";

interface SidebarPromoProps {
  price: number;
}

export function SidebarPromo({ price }: SidebarPromoProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) setIsCollapsed(JSON.parse(stored));
  }, []);

  const handleCollapse = () => {
    const newState = true;
    setIsCollapsed(newState);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(newState));
  };

  return (
    <div
      className={`flex flex-col justify-center transition-all duration-200 ${
        isCollapsed
          ? "w-full px-1 mb-2 mt-1"
          : "mb-2 h-fit w-fit rounded-2xl bg-zinc-800 p-4 pt-1"
      }`}
    >
      {!isCollapsed && (
        <>
          <div className="flex w-full justify-between items-center gap-1 group">
            <div className="font-medium text-sm">Go on, You Deserve This</div>
            <Button
              isIconOnly
              variant="light"
              size="sm"
              className="p-0! text-zinc-400 hover:text-white relative left-2 group-hover:opacity-100 opacity-0 transition"
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

      <Link href="/pricing" className={isCollapsed ? "w-full" : "mt-2"}>
        <RaisedButton
          className="w-full rounded-xl! text-black!"
          color="#00bbff"
          size={"sm"}
        >
          <ZapIcon fill="black" width={17} height={17} />
          Upgrade to Pro
        </RaisedButton>
      </Link>
    </div>
  );
}
