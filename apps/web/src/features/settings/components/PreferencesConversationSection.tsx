"use client";

import type { SharedSelection } from "@heroui/react";
import { Select, SelectItem } from "@heroui/react";
import { CustomResponseStyleInput } from "@/features/settings/components/CustomResponseStyleInput";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { responseStyleOptions } from "./preferencesOptions";

interface PreferencesConversationSectionProps {
  responseStyle: string;
  isUpdating: boolean;
  onResponseStyleChange: (keys: SharedSelection) => void;
  onCustomResponseStyleChange: (value: string) => void;
}

export function PreferencesConversationSection({
  responseStyle,
  isUpdating,
  onResponseStyleChange,
  onCustomResponseStyleChange,
}: PreferencesConversationSectionProps) {
  const isCustom =
    !!responseStyle &&
    !responseStyleOptions.some((option) => option.value === responseStyle);

  return (
    <SettingsSection title="Conversation">
      <SettingsRow label="Response Style" stacked>
        <Select
          placeholder="Select response style"
          selectedKeys={
            responseStyle
              ? responseStyleOptions.some(
                  (option) => option.value === responseStyle,
                )
                ? new Set([responseStyle])
                : new Set(["other"])
              : new Set()
          }
          disallowEmptySelection={false}
          onSelectionChange={onResponseStyleChange}
          isDisabled={isUpdating}
          classNames={{
            trigger:
              "bg-zinc-800/50 hover:bg-zinc-700/50 cursor-pointer min-h-[36px]",
            popoverContent: "bg-zinc-800 z-50",
            listbox: "bg-zinc-800",
            value: "text-white text-sm",
          }}
        >
          {responseStyleOptions.map((style) => (
            <SelectItem
              key={style.value}
              textValue={
                style.value.charAt(0).toUpperCase() + style.value.slice(1)
              }
            >
              <div>
                <div className="text-sm font-medium">
                  {style.value.charAt(0).toUpperCase() + style.value.slice(1)}
                </div>
                <div className="text-xs text-zinc-500">
                  {style.label.split(" - ")[1]}
                </div>
              </div>
            </SelectItem>
          ))}
        </Select>
        {isCustom && (
          <CustomResponseStyleInput
            value={responseStyle}
            onChange={onCustomResponseStyleChange}
            isDisabled={isUpdating}
          />
        )}
      </SettingsRow>
    </SettingsSection>
  );
}
