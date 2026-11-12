/**
 * TriggerSelectToggle Component
 *
 * Wrapper that toggles between Select dropdown and manual tag input
 */

"use client";

import { Input, ListBox, Select } from "@heroui/react";
import { useState } from "react";
import { inputVariants } from "@/components/shared/controlVariants";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { TriggerTagInput } from "./TriggerTagInput";
import type { TriggerSelectToggleProps } from "./types";

export function TriggerSelectToggle({
  label,
  selectProps,
  tagInputProps,
  searchConfig,
  allowManualInput = true,
}: TriggerSelectToggleProps) {
  const [useManualInput, setUseManualInput] = useState(false);

  const {
    options,
    selectedValues,
    onSelectionChange,
    isLoading,
    placeholder = "Select items",
    renderValue,
    description,
  } = selectProps;

  if (!allowManualInput || !useManualInput) {
    const selected = new Set(selectedValues);
    const selectedItems = options.flatMap((option) =>
      selected.has(option.value)
        ? [{ key: option.value, textValue: option.label }]
        : [],
    );

    const valueContent = renderValue
      ? renderValue(selectedItems)
      : selectedItems.length > 0
        ? `${selectedItems.length} selected`
        : isLoading
          ? "Loading..."
          : placeholder;

    return (
      <div className="space-y-2">
        {searchConfig?.enabled && (
          <Input
            aria-label={`Search ${label}`}
            placeholder={searchConfig.placeholder || "Type to search..."}
            value={searchConfig.searchValue}
            onChange={(e) => searchConfig.onSearchChange(e.target.value)}
            className={inputVariants({ size: "sm", className: "w-full" })}
          />
        )}
        <Select
          aria-label={label}
          placeholder={isLoading ? "Loading..." : placeholder}
          selectionMode="multiple"
          value={selectedValues}
          onChange={(keys) => {
            onSelectionChange(keys.map(String));
          }}
          className={fieldVariants({
            labelPlacement: "inside",
            className: "w-full",
          })}
        >
          <Select.Trigger className="w-full">
            <GaiaSelectValue>{valueContent}</GaiaSelectValue>
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {isLoading && options.length === 0 ? (
                <GaiaListBoxItem id="loading" isDisabled textValue="Loading...">
                  Loading...
                </GaiaListBoxItem>
              ) : (
                options.map((option) => (
                  <GaiaListBoxItem
                    key={option.value}
                    id={option.value}
                    textValue={option.label}
                  >
                    {option.label}
                  </GaiaListBoxItem>
                ))
              )}
            </ListBox>
          </Select.Popover>
        </Select>
        {(description || allowManualInput) && (
          <div className="flex justify-between items-center">
            {description || <span className="text-xs text-zinc-500" />}
            {allowManualInput && (
              <button
                type="button"
                onClick={() => setUseManualInput(true)}
                className="text-xs text-primary hover:underline cursor-pointer"
              >
                Or enter manually
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <TriggerTagInput
      values={tagInputProps.values}
      onChange={tagInputProps.onChange}
      placeholder={tagInputProps.placeholder}
      emptyPlaceholder={tagInputProps.emptyPlaceholder}
      validate={tagInputProps.validate}
      formatTag={tagInputProps.formatTag}
      description={
        <button
          type="button"
          onClick={() => setUseManualInput(false)}
          className="text-primary/90 hover:text-primary font-medium hover:underline cursor-pointer transition-colors"
        >
          Back to list
        </button>
      }
    />
  );
}
