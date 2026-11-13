"use client";

import { Popover } from "@heroui/react";
import { ArrowDown01Icon } from "@icons";
import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
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
  onOpenChange?: (isOpen: boolean) => void;
  children:
    | React.ReactNode
    | ((props: { onClose: () => void }) => React.ReactNode);
  className?: string;
}

type FieldChipVariant = NonNullable<BaseFieldChipProps["variant"]>;

const VALUE_TEXT_CLASS: Record<FieldChipVariant, string> = {
  default: "",
  secondary: "",
  primary: "text-blue-400",
  success: "text-green-400",
  warning: "text-yellow-400",
  danger: "text-red-400",
};

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

  const valueTextClass = hasValue ? VALUE_TEXT_CLASS[variant] : "";

  return (
    <Popover
      isOpen={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open);
        onOpenChange?.(open);
      }}
    >
      <GaiaButton
        variant="tertiary"
        tone={hasValue ? "bright" : "faint"}
        hoverTone={hasValue ? "none" : "muted"}
        size="sm"
        aria-label={`${label} selection. Current value: ${hasValue ? (typeof value === "string" ? value : "selected") : "none selected"}`}
        className={cn(
          "h-8 min-w-0 gap-1 border-0 font-normal shadow-none ring-0 transition-all outline-none focus:ring-0 focus:outline-none",
          valueTextClass,
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
      </GaiaButton>
      <Popover.Content
        placement="bottom start"
        className="min-w-68 max-w-68 shadow-xl"
      >
        <Popover.Arrow />
        <div className="flex w-full justify-start pl-4 pt-3 text-xs font-medium text-zinc-400">
          {label}
        </div>
        <div className="w-full">
          {typeof children === "function"
            ? children({ onClose: () => setIsOpen(false) })
            : children}
        </div>
      </Popover.Content>
    </Popover>
  );
}
