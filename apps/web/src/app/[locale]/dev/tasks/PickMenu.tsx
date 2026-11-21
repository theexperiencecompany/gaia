"use client";

import { Dropdown } from "@heroui/react";
import { ArrowDown01Icon, Tick02Icon } from "@icons";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";

/**
 * A choice from a short list, as a 36px editor control that opens a menu. Picking
 * toggles an option; one that takes several keeps the menu open.
 */
export default function PickMenu({
  label,
  summary,
  isPlaceholder = false,
  options,
  selected,
  isMultiple,
  onPick,
}: {
  label: string;
  summary: string;
  isPlaceholder?: boolean;
  options: { id: string; label: string }[];
  selected: string[];
  isMultiple: boolean;
  onPick: (id: string) => void;
}) {
  return (
    <Dropdown>
      <GaiaButton
        size="sm"
        variant="sunken"
        shape="md"
        tone={isPlaceholder ? "muted" : "strong"}
        inset="tight"
        aria-label={label}
        className="h-9 w-44 min-w-0 justify-between gap-2 text-sm"
      >
        <span className="truncate">{summary}</span>
        <ArrowDown01Icon className="size-4 shrink-0 opacity-60" />
      </GaiaButton>
      <Dropdown.Popover
        placement="bottom end"
        offset={6}
        className={shapeVariants({ shape: "lg", className: "min-w-44" })}
      >
        <Dropdown.Menu
          aria-label={label}
          shouldCloseOnSelect={!isMultiple}
          onAction={(key) => onPick(String(key))}
        >
          {options.map((option) => (
            <Dropdown.Item
              key={option.id}
              id={option.id}
              textValue={option.label}
              className="gap-2"
            >
              {option.label}
              {selected.includes(option.id) && (
                <Tick02Icon className="ml-auto size-4 text-zinc-400" />
              )}
            </Dropdown.Item>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  );
}
