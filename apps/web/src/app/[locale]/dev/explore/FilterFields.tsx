"use client";

import { InputGroup, ListBox, Select } from "@heroui/react";
import { Cancel01Icon, Search01Icon } from "@icons";
import type { ReactNode } from "react";

import {
  inputVariants,
  overlayVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { toneVariants } from "@/components/shared/tone";
import { cn } from "@/lib/utils";
import { ALL } from "./useExplore";

/** A 36px search box; Escape or the clear button empties it. */
export function SearchField({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
}) {
  return (
    <InputGroup
      className={inputVariants({
        variant: "sunken",
        className: cn("min-w-0", className),
      })}
    >
      <InputGroup.Prefix>
        <Search01Icon className="size-4 shrink-0 text-zinc-500" />
      </InputGroup.Prefix>
      <InputGroup.Input
        aria-label={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") onChange("");
        }}
        placeholder={placeholder}
        className={toneVariants({ tone: "white", className: "text-sm" })}
      />
      {value && (
        <InputGroup.Suffix>
          <GaiaButton
            isIconOnly
            size="sm"
            variant="raised-ghost"
            tone="faint"
            hoverTone="bright"
            aria-label="Clear search"
            onPress={() => onChange("")}
            className="size-7 min-w-7"
          >
            <Cancel01Icon className="size-3.5" />
          </GaiaButton>
        </InputGroup.Suffix>
      )}
    </InputGroup>
  );
}

export interface FilterOption {
  id: string;
  label: string;
  icon?: ReactNode;
}

/** One narrowing choice as a select: "any" first; an option's icon leads so it is found by sight. */
export function FilterSelect({
  label,
  anyLabel,
  options,
  value,
  onChange,
  className,
}: {
  label: string;
  anyLabel: string;
  options: FilterOption[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  const selected = options.find((option) => option.id === value);
  return (
    <Select
      aria-label={label}
      selectedKey={value}
      onSelectionChange={(key) => onChange(String(key ?? ALL))}
      className={className}
    >
      <Select.Trigger
        className={inputVariants({
          variant: "sunken",
          className: "w-full cursor-pointer gap-2",
        })}
      >
        {selected?.icon}
        <GaiaSelectValue
          className={toneVariants({ tone: "white", className: "text-sm" })}
        />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover
        className={overlayVariants({
          surface: "raised",
          className: "min-w-52",
        })}
      >
        <ListBox>
          <GaiaListBoxItem id={ALL} textValue={anyLabel} />
          {options.map((option) => (
            <GaiaListBoxItem
              key={option.id}
              id={option.id}
              textValue={option.label}
            >
              <span className="flex min-w-0 items-center gap-2">
                {option.icon}
                <span className="truncate">{option.label}</span>
              </span>
            </GaiaListBoxItem>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
