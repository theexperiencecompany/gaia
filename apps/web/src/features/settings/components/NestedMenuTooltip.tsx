"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import type { ReactNode } from "react";

interface MenuItem {
  key: string;
  label: string;
  icon?: React.ElementType;
  iconElement?: ReactNode;
  action: () => void;
}

interface NestedMenuTooltipProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  itemRef: HTMLElement | null;
  menuItems: MenuItem[];
  iconClasses?: string;
}

export function NestedMenuTooltip({
  isOpen,
  onOpenChange,
  itemRef,
  menuItems,
  iconClasses = "w-[18px] h-[18px]",
}: NestedMenuTooltipProps) {
  if (!itemRef) return null;

  return (
    <Tooltip
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      placement="right-start"
      offset={8}
      closeDelay={0}
      classNames={{
        content: "p-0 bg-secondary-bg border-0! outline-0!",
        base: "border-0",
      }}
      content={
        <div
          className="flex flex-col p-1"
          onMouseEnter={() => onOpenChange(true)}
          onMouseLeave={() => onOpenChange(false)}
        >
          {menuItems.map((item) => {
            const Icon = item.icon;
            const iconContent = item.iconElement ? (
              item.iconElement
            ) : Icon ? (
              <Icon className={iconClasses} />
            ) : null;

            return (
              <Button
                key={item.key}
                variant="light"
                size="sm"
                className="justify-start text-sm text-zinc-400 transition hover:text-white"
                onPress={() => {
                  item.action();
                  onOpenChange(false);
                }}
                startContent={iconContent}
              >
                {item.label}
              </Button>
            );
          })}
        </div>
      }
    >
      <div
        style={{
          position: "fixed",
          left: itemRef.getBoundingClientRect().right,
          top: itemRef.getBoundingClientRect().top,
          width: 1,
          height: 1,
          pointerEvents: "none",
        }}
      />
    </Tooltip>
  );
}
