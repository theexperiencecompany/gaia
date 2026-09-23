"use client";

import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/react";
import { ArrowDown01Icon } from "@icons";
import { useState } from "react";
import { cn } from "@/lib/utils";

interface BaseFieldChipProps {
  label: string;
  value?: string | React.ReactElement;
  placeholder: string;
  icon?: React.ReactElement;
  variant?:
    | "default"
    | "primary"
    | "secondary"
    | "success"
    | "warning"
    | "danger";
  isActive?: boolean;
  onOpenChange?: (isOpen: boolean) => void;
  children:
    | React.ReactNode
    | ((props: { onClose: () => void }) => React.ReactNode);
  className?: string;
}

export default function BaseFieldChip({
  label,
  value,
  placeholder,
  icon,
  variant = "default",
  onOpenChange,
  children,
  className,
}: BaseFieldChipProps) {
  const [isOpen, setIsOpen] = useState(false);

  const hasValue = value !== undefined && value !== null && value !== "";

  return (
    <Popover
      isOpen={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open);
        onOpenChange?.(open);
      }}
      placement="bottom-start"
      showArrow={true}
      shouldCloseOnBlur={true}
    >
      <PopoverTrigger>
        <Button
          variant="flat"
          color={hasValue ? variant : "default"}
          size="sm"
          aria-label={`${label} selection. Current value: ${hasValue ? (typeof value === "string" ? value : "selected") : "none selected"}`}
          className={cn(
            "h-8 min-w-0 font-normal transition-all",
            !hasValue && "text-zinc-500",
            className,
          )}
        >
          {icon}
          <span className="max-w-[120px] truncate">
            {hasValue ? (
              value
            ) : (
              <span className="text-zinc-400">{placeholder}</span>
            )}
          </span>
          <ArrowDown01Icon
            size={14}
            className={cn("transition-transform", isOpen && "rotate-180")}
          />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="min-w-68 max-w-68">
        <div className="flex w-full justify-start pl-4 pt-3 text-xs font-medium text-zinc-400">
          {label}
        </div>
        <div className="w-full">
          {typeof children === "function"
            ? children({ onClose: () => setIsOpen(false) })
            : children}
        </div>
      </PopoverContent>
    </Popover>
  );
}
