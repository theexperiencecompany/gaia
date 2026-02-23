"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import type { ReactElement } from "react";

interface MenuItem {
  iconElement?: ReactElement;
  key: string;
  label: string;
  description?: string;
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
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
                className="justify-start text-sm text-foreground-500 transition hover:text-foreground-900 h-auto py-2"
                onPress={() => {
                  item.action();
                  onOpenChange(false);
                }}
                startContent={iconContent}
              >
                <div className="flex flex-col items-start">
                  <span>{item.label}</span>
                  {item.description && (
                    <span className="text-xs text-foreground-400 font-normal">
                      {item.description}
                    </span>
                  )}
                </div>
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
