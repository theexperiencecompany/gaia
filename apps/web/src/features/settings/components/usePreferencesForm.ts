"use client";

import type { SharedSelection } from "@heroui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { authApi } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { mergedOnboardingUpdate } from "@/features/settings/utils/onboardingPreferences";
import { toast } from "@/lib/toast";
import {
  getCurrentBrowserTimezone,
  normalizeTimezone,
} from "@/utils/timezoneUtils";

export interface PreferencesState {
  profession: string;
  response_style: string;
  timezone: string;
}

export function usePreferencesForm() {
  const user = useUser();
  const { updateUser } = useUserActions();
  const [isUpdating, setIsUpdating] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  const [preferences, setPreferences] = useState<PreferencesState>({
    profession: user.onboarding?.preferences?.profession || "",
    response_style: user.onboarding?.preferences?.response_style || "",
    timezone: normalizeTimezone(user.timezone || "UTC"),
  });

  const updateTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastSavedPreferences = useRef(preferences);

  const updateTimezone = useCallback(
    async (timezone: string) => {
      try {
        const response = await authApi.updateUserTimezone(timezone || "");
        if (response.success) {
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
    async (updatedPreferences: PreferencesState) => {
      try {
        setIsUpdating(true);
        setHasUnsavedChanges(false);

        const { timezone, profession, response_style } = updatedPreferences;

        const response = await authApi.updateOnboardingPreferences({
          profession,
          response_style,
        });

        if (response.success) {
          updateUser(
            mergedOnboardingUpdate(user.onboarding, {
              profession: profession || undefined,
              response_style: response_style || undefined,
            }),
          );

          if (timezone !== lastSavedPreferences.current.timezone) {
            await updateTimezone(timezone);
          }

          toast.success("Preferences saved");
          lastSavedPreferences.current = updatedPreferences;
        } else {
          setPreferences(lastSavedPreferences.current);
          setHasUnsavedChanges(true);
          toast.error("Failed to save preferences");
        }
      } catch (error) {
        console.error("Error updating preferences:", error);
        setPreferences(lastSavedPreferences.current);
        setHasUnsavedChanges(true);
        toast.error("Failed to save preferences");
      } finally {
        setIsUpdating(false);
      }
    },
    [updateTimezone, updateUser, user.onboarding],
  );

  const debouncedUpdate = useCallback(
    (updatedPreferences: PreferencesState) => {
      if (updateTimeoutRef.current) {
        clearTimeout(updateTimeoutRef.current);
      }
      setHasUnsavedChanges(true);
      updateTimeoutRef.current = setTimeout(() => {
        updatePreferences(updatedPreferences);
      }, 1000);
    },
    [updatePreferences],
  );

  const handleProfessionChange = (keys: SharedSelection) => {
    const profession =
      keys !== "all" && keys.size > 0 ? (Array.from(keys)[0] as string) : "";
    const updated = { ...preferences, profession };
    setPreferences(updated);
    debouncedUpdate(updated);
  };

  const handleResponseStyleChange = (keys: SharedSelection) => {
    let responseStyle = "";
    if (keys !== "all" && keys.size > 0) {
      const raw = Array.from(keys)[0] as string;
      responseStyle = raw === "other" ? "custom" : raw;
    }
    const updated = { ...preferences, response_style: responseStyle };
    setPreferences(updated);
    debouncedUpdate(updated);
  };

  const handleCustomResponseStyleChange = (customStyle: string) => {
    const updated = { ...preferences, response_style: customStyle };
    setPreferences(updated);
    debouncedUpdate(updated);
  };

  const handleTimezoneChange = (keys: SharedSelection) => {
    const selectedKeys = Array.from(keys);
    const timezoneValue = (selectedKeys[0] as string) || "UTC";
    const updated = { ...preferences, timezone: timezoneValue };
    setPreferences(updated);
    debouncedUpdate(updated);
  };

  const handleAutoDetectTimezone = () => {
    const browserTimezone = getCurrentBrowserTimezone();
    const updated = { ...preferences, timezone: browserTimezone.value };
    setPreferences(updated);
    debouncedUpdate(updated);
    toast.success(`Timezone set to ${browserTimezone.label}`);
  };

  useEffect(() => {
    return () => {
      if (updateTimeoutRef.current) {
        clearTimeout(updateTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const newPreferences: PreferencesState = {
      profession: user.onboarding?.preferences?.profession || "",
      response_style: user.onboarding?.preferences?.response_style || "",
      timezone: normalizeTimezone(user.timezone || "") || "UTC",
    };
    setPreferences(newPreferences);
    lastSavedPreferences.current = newPreferences;
  }, [user.onboarding?.preferences, user.timezone]);

  return {
    preferences,
    isUpdating,
    hasUnsavedChanges,
    handleProfessionChange,
    handleResponseStyleChange,
    handleCustomResponseStyleChange,
    handleTimezoneChange,
    handleAutoDetectTimezone,
  };
}
