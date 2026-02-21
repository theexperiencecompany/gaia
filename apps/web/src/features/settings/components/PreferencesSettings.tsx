"use client";

import {
  Button,
  Select,
  SelectItem,
  type SharedSelection,
  Textarea,
} from "@heroui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { authApi } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { CustomResponseStyleInput } from "@/features/settings/components/CustomResponseStyleInput";
import { StatusIndicator } from "@/features/settings/components/StatusIndicator";
import {
  SettingsPage,
  SettingsRow,
  SettingsSection,
} from "@/features/settings/components/ui";
import {
  getCurrentBrowserTimezone,
  getTimezoneList,
  normalizeTimezone,
} from "@/utils/timezoneUtils";

import type { ModalAction } from "./SettingsMenu";

const responseStyleOptions = [
  { value: "brief", label: "Brief - Keep responses concise and to the point" },
  { value: "detailed", label: "Detailed - Provide comprehensive explanations" },
  { value: "casual", label: "Casual - Use a friendly and informal tone" },
  {
    value: "professional",
    label: "Professional - Maintain a formal and business-like tone",
  },
  { value: "other", label: "Other - Define your own response style" },
];

const professionOptions = [
  { value: "student", label: "Student" },
  { value: "developer", label: "Software Developer" },
  { value: "designer", label: "Designer" },
  { value: "manager", label: "Manager" },
  { value: "entrepreneur", label: "Entrepreneur" },
  { value: "consultant", label: "Consultant" },
  { value: "researcher", label: "Researcher" },
  { value: "teacher", label: "Teacher" },
  { value: "writer", label: "Writer" },
  { value: "analyst", label: "Analyst" },
  { value: "engineer", label: "Engineer" },
  { value: "marketer", label: "Marketer" },
  { value: "other", label: "Other" },
];

export default function PreferencesSettings({
  setModalAction,
}: {
  setModalAction: React.Dispatch<React.SetStateAction<ModalAction | null>>;
}) {
  const user = useUser();
  const { updateUser } = useUserActions();
  const [isUpdating, setIsUpdating] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  // Get timezone options with enhanced display
  const timezoneOptions = getTimezoneList().map((tz) => ({
    value: tz.value,
    label: tz.formattedLabel,
  }));

  const [preferences, setPreferences] = useState({
    profession: user.onboarding?.preferences?.profession || "",
    response_style: user.onboarding?.preferences?.response_style || "",
    custom_instructions:
      user.onboarding?.preferences?.custom_instructions || null,
    timezone: normalizeTimezone(user.timezone || "UTC"),
  });

  const updateTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastSavedPreferences = useRef(preferences);

  // Separate function to update timezone
  const updateTimezone = useCallback(
    async (timezone: string) => {
      try {
        const response = await authApi.updateUserTimezone(timezone || "");
        if (response.success) {
          // Update user state with new timezone
          updateUser({ timezone: timezone || undefined });
        }
      } catch (error) {
        console.error("Error updating timezone:", error);
        throw error;
      }
    },
    [updateUser],
  );

  const updatePreferences = useCallback(
    async (updatedPreferences: typeof preferences) => {
      try {
        setIsUpdating(true);
        setHasUnsavedChanges(false);

        // Extract timezone for separate handling
        const { timezone, ...preferencesWithoutTimezone } = updatedPreferences;

        // Filter out empty strings and only send valid values for non-timezone preferences
        const sanitizedPreferences = Object.entries(
          preferencesWithoutTimezone,
        ).reduce(
          (acc, [key, value]) => {
            // Only include non-empty values, convert empty strings to undefined
            if (value !== "" && value !== null && value !== undefined)
              acc[key] = value;
            else if (value === null) acc[key] = null;
            // Explicitly include null values (for custom_instructions)

            return acc;
          },
          {} as Record<string, string | null>,
        );

        // Update preferences (without timezone)
        const response =
          await authApi.updateOnboardingPreferences(sanitizedPreferences);

        if (response.success) {
          // If timezone changed, update it separately
          if (timezone !== lastSavedPreferences.current.timezone) {
            await updateTimezone(timezone);
          }

          toast.success("Preferences saved");
          lastSavedPreferences.current = updatedPreferences;
        } else {
          // Rollback on failure
          setPreferences(lastSavedPreferences.current);
          setHasUnsavedChanges(true);
          toast.error("Failed to save preferences");
        }
      } catch (error) {
        console.error("Error updating preferences:", error);
        // Rollback on failure
        setPreferences(lastSavedPreferences.current);
        setHasUnsavedChanges(true);
        toast.error("Failed to save preferences");
      } finally {
        setIsUpdating(false);
      }
    },
    [updateTimezone],
  );

  // Debounced update function
  const debouncedUpdate = useCallback(
    (updatedPreferences: typeof preferences) => {
      if (updateTimeoutRef.current) {
        clearTimeout(updateTimeoutRef.current);
      }

      setHasUnsavedChanges(true);

      updateTimeoutRef.current = setTimeout(() => {
        updatePreferences(updatedPreferences);
      }, 1000); // Wait 1 second after user stops typing
    },
    [updatePreferences],
  );

  const handleProfessionChange = (keys: SharedSelection) => {
    if (keys !== "all" && keys.size > 0) {
      const profession = Array.from(keys)[0] as string;
      const updatedPreferences = { ...preferences, profession };
      setPreferences(updatedPreferences);
      debouncedUpdate(updatedPreferences);
    } else {
      // Handle case when profession is deselected
      const updatedPreferences = { ...preferences, profession: "" };
      setPreferences(updatedPreferences);
      debouncedUpdate(updatedPreferences);
    }
  };

  const handleResponseStyleChange = (keys: SharedSelection) => {
    if (keys !== "all" && keys.size > 0) {
      const responseStyle = Array.from(keys)[0] as string;
      const updatedPreferences = {
        ...preferences,
        response_style: responseStyle === "other" ? "custom" : responseStyle,
      };
      setPreferences(updatedPreferences);
      debouncedUpdate(updatedPreferences);
    } else {
      // Handle case when response style is deselected
      const updatedPreferences = { ...preferences, response_style: "" };
      setPreferences(updatedPreferences);
      debouncedUpdate(updatedPreferences);
    }
  };

  const handleCustomResponseStyleChange = (customStyle: string) => {
    const updatedPreferences = {
      ...preferences,
      response_style: customStyle,
    };
    setPreferences(updatedPreferences);
    debouncedUpdate(updatedPreferences);
  };

  const handleCustomInstructionsChange = (customInstructions: string) => {
    // Convert empty strings to null for backend
    const instructions =
      customInstructions.trim() === "" ? null : customInstructions;
    const updatedPreferences = {
      ...preferences,
      custom_instructions: instructions,
    };
    setPreferences(updatedPreferences);
    debouncedUpdate(updatedPreferences);
  };

  const handleTimezoneChange = (keys: SharedSelection) => {
    const selectedKeys = Array.from(keys);
    const timezoneValue = selectedKeys[0] as string;
    const updatedPreferences = {
      ...preferences,
      timezone: timezoneValue || "UTC", // Default to UTC if empty
    };
    setPreferences(updatedPreferences);
    debouncedUpdate(updatedPreferences);
  };

  const handleAutoDetectTimezone = () => {
    const browserTimezone = getCurrentBrowserTimezone();
    const updatedPreferences = {
      ...preferences,
      timezone: browserTimezone.value,
    };
    setPreferences(updatedPreferences);
    debouncedUpdate(updatedPreferences);
    toast.success(`Timezone set to ${browserTimezone.label}`);
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (updateTimeoutRef.current) {
        clearTimeout(updateTimeoutRef.current);
      }
    };
  }, []);

  // Update preferences when user data changes
  useEffect(() => {
    const newPreferences = {
      profession: user.onboarding?.preferences?.profession || "",
      response_style: user.onboarding?.preferences?.response_style || "",
      custom_instructions:
        user.onboarding?.preferences?.custom_instructions || null,
      timezone: normalizeTimezone(user.timezone || "") || "UTC", // Normalize legacy timezone names
    };
    setPreferences(newPreferences);
    lastSavedPreferences.current = newPreferences;
  }, [user.onboarding?.preferences, user.timezone]);

  return (
    <SettingsPage>
      <SettingsSection title="Identity">
        <SettingsRow label="Profession" stacked>
          <Select
            placeholder="Select your profession"
            selectedKeys={
              preferences.profession
                ? new Set([preferences.profession])
                : new Set()
            }
            onSelectionChange={handleProfessionChange}
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
              onPress={handleAutoDetectTimezone}
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
              onSelectionChange={handleTimezoneChange}
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

      <SettingsSection title="Conversation">
        <SettingsRow label="Response Style" stacked>
          <Select
            placeholder="Select response style"
            selectedKeys={
              preferences.response_style
                ? responseStyleOptions.some(
                    (option) => option.value === preferences.response_style,
                  )
                  ? new Set([preferences.response_style])
                  : new Set(["other"])
                : new Set()
            }
            disallowEmptySelection={false}
            onSelectionChange={handleResponseStyleChange}
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
          {preferences.response_style &&
            !responseStyleOptions.some(
              (option) => option.value === preferences.response_style,
            ) && (
              <CustomResponseStyleInput
                value={preferences.response_style}
                onChange={handleCustomResponseStyleChange}
                isDisabled={isUpdating}
              />
            )}
        </SettingsRow>

        <SettingsRow
          label="Custom Instructions"
          description="These instructions will be included in every conversation."
          stacked
        >
          <Textarea
            placeholder="Add any specific instructions for how GAIA should assist you..."
            value={preferences.custom_instructions || ""}
            onChange={(e) => handleCustomInstructionsChange(e.target.value)}
            isDisabled={isUpdating}
            minRows={3}
            classNames={{
              input: "bg-zinc-800/50 text-sm",
              inputWrapper: "bg-zinc-800/50 hover:bg-zinc-700/50",
            }}
          />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection>
        <SettingsRow
          label="Clear Chat History"
          description="Permanently delete all your conversations and chat history"
          variant="danger"
        >
          <Button
            variant="flat"
            color="danger"
            onPress={() => setModalAction("clear_chats")}
          >
            Clear All
          </Button>
        </SettingsRow>
      </SettingsSection>

      <StatusIndicator
        isUpdating={isUpdating}
        hasUnsavedChanges={hasUnsavedChanges}
      />
    </SettingsPage>
  );
}
