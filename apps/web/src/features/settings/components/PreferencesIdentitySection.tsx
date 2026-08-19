"use client";

import type { SharedSelection } from "@heroui/react";
import { Button, Select, SelectItem } from "@heroui/react";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { getCurrentBrowserTimezone } from "@/utils/timezoneUtils";
import { professionOptions } from "./preferencesOptions";
import type { PreferencesState } from "./usePreferencesForm";

interface PreferencesIdentitySectionProps {
  preferences: PreferencesState;
  timezoneOptions: { value: string; label: string }[];
  isUpdating: boolean;
  onProfessionChange: (keys: SharedSelection) => void;
  onTimezoneChange: (keys: SharedSelection) => void;
  onAutoDetectTimezone: () => void;
}

export function PreferencesIdentitySection({
  preferences,
  timezoneOptions,
  isUpdating,
  onProfessionChange,
  onTimezoneChange,
  onAutoDetectTimezone,
}: PreferencesIdentitySectionProps) {
  return (
    <SettingsSection title="Identity">
      <SettingsRow label="Profession" stacked>
        <Select
          placeholder="Select your profession"
          selectedKeys={
            preferences.profession
              ? new Set([preferences.profession])
              : new Set()
          }
          onSelectionChange={onProfessionChange}
          isDisabled={isUpdating}
          classNames={{
            trigger:
              "bg-zinc-800/50 hover:bg-zinc-700/50 cursor-pointer min-h-[36px]",
            popoverContent: "bg-zinc-800 z-50",
            listbox: "bg-zinc-800",
            value: "text-white text-sm",
          }}
        >
          {professionOptions.map((profession) => (
            <SelectItem key={profession.value} textValue={profession.label}>
              {profession.label}
            </SelectItem>
          ))}
        </Select>
      </SettingsRow>

      <SettingsRow
        label="Timezone"
        description={
          getCurrentBrowserTimezone().currentTime
            ? `Current time: ${getCurrentBrowserTimezone().currentTime}`
            : undefined
        }
        stacked
      >
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="flat"
            onPress={onAutoDetectTimezone}
            isDisabled={isUpdating}
            className="border-zinc-700 bg-zinc-800/50 text-zinc-300 hover:bg-zinc-700/50"
          >
            Auto Detect
          </Button>
          <Select
            placeholder="Select your timezone"
            selectedKeys={
              preferences.timezone
                ? new Set([preferences.timezone])
                : new Set(["UTC"])
            }
            onSelectionChange={onTimezoneChange}
            isDisabled={isUpdating}
            classNames={{
              trigger:
                "bg-zinc-800/50 hover:bg-zinc-700/50 cursor-pointer min-h-[36px]",
              popoverContent: "bg-zinc-800 z-50",
              listbox: "bg-zinc-800",
              value: "text-white text-sm",
            }}
          >
            {timezoneOptions.map((timezone) => (
              <SelectItem key={timezone.value} textValue={timezone.label}>
                {timezone.label}
              </SelectItem>
            ))}
          </Select>
        </div>
      </SettingsRow>
    </SettingsSection>
  );
}
