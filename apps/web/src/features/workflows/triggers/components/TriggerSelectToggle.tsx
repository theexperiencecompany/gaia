/**
 * TriggerSelectToggle Component
 *
 * Wrapper that toggles between Select dropdown and manual tag input
 */

"use client";

import { Input } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { useState } from "react";

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
    return (
      <>
        {searchConfig?.enabled && (
          <Input
            label={`Search ${label}`}
            placeholder={searchConfig.placeholder || "Type to search..."}
            value={searchConfig.searchValue}
            onValueChange={searchConfig.onSearchChange}
            className="w-full max-w-xl"
            size="sm"
            isClearable
            onClear={() => searchConfig.onSearchChange("")}
          />
        )}
        <Select
          label={label}
          placeholder={isLoading ? "Loading..." : placeholder}
          selectionMode="multiple"
          selectedKeys={new Set(selectedValues)}
          onSelectionChange={(keys) => {
            const selected = Array.from(keys) as string[];
            onSelectionChange(selected);
          }}
          isLoading={isLoading}
          renderValue={renderValue}
          className="w-full max-w-xl"
          description={
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
          }
        >
          {isLoading && options.length === 0 ? (
            <SelectItem key="loading" isDisabled>
              Loading...
            </SelectItem>
          ) : (
            options.map((option) => (
              <SelectItem key={option.value} textValue={option.label}>
                {option.label}
              </SelectItem>
            ))
          )}
        </Select>
      </>
    );
  }

  return (
    <TriggerTagInput
      label={label}
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
