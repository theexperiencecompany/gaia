"use client";

import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/react";
import { useState } from "react";

import { ArrowDown01Icon } from "@/icons";
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
  isActive = false,
  onOpenChange,
  children,
  className,
}: BaseFieldChipProps) {
  const [isOpen, setIsOpen] = useState(false);

  const hasValue = value !== undefined && value !== null && value !== "";

  // Flat design with consistent zinc background
  const getButtonClassName = () => {
    const baseClasses = "border-0 shadow-none outline-none focus:outline-none";

    if (hasValue) {
      switch (variant) {
        case "success":
          return `${baseClasses} bg-surface-200 text-green-500 hover:bg-surface-300`;
        case "primary":
          return `${baseClasses} bg-surface-200 text-blue-500 hover:bg-surface-300`;
        case "warning":
          return `${baseClasses} bg-surface-200 text-yellow-500 hover:bg-surface-300`;
        case "danger":
          return `${baseClasses} bg-surface-200 text-red-500 hover:bg-surface-300`;
        default:
          return `${baseClasses} bg-surface-200 text-foreground-900 hover:bg-surface-300`;
      }
    }
    return `${baseClasses} bg-surface-200 text-foreground-500 hover:bg-surface-300 hover:text-foreground-700`;
  };

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
          variant="light"
          size="sm"
          aria-label={`${label} selection. Current value: ${hasValue ? (typeof value === "string" ? value : "selected") : "none selected"}`}
          className={cn(
            "h-8 min-w-0 gap-1 border-0 px-3 font-normal ring-0 transition-all outline-none focus:ring-0 focus:outline-none",
            isOpen && "ring-0",
            isActive && "ring-0",
            !hasValue && "text-foreground-500",
            getButtonClassName(),
            className,
          )}
        >
          {icon}
          <span className="max-w-[120px] truncate">
            {hasValue ? (
              value
            ) : (
              <span className="text-foreground-400">{placeholder}</span>
            )}
          </span>
          <ArrowDown01Icon
            size={14}
            className={cn("transition-transform", isOpen && "rotate-180")}
          />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="min-w-68 max-w-68 rounded-2xl border-border-surface-700 bg-surface-100 p-0 shadow-xl">
        <div className="flex w-full justify-start pl-4 pt-3 text-xs font-medium text-foreground-400">
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
