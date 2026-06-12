import { useCallback, useEffect, useRef, useState } from "react";
import { authApi } from "@/features/auth/api/authApi";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { mergedOnboardingUpdate } from "@/features/settings/utils/onboardingPreferences";
import { toast } from "@/lib/toast";

const SAVE_DEBOUNCE_MS = 1000;

/**
 * The user-level custom instructions included in every conversation.
 *
 * The backend replaces the whole onboarding preferences object on save, so
 * the payload always carries profession/response_style from the store, and a
 * successful save writes the result back to the store to keep the
 * Preferences page consistent.
 */
export const useGlobalCustomInstructions = () => {
  const user = useUser();
  const { updateUser } = useUserActions();

  const stored = user.onboarding?.preferences?.custom_instructions || "";
  const [value, setValue] = useState(stored);
  const [isSaving, setIsSaving] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    setValue(stored);
  }, [stored]);

  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, []);

  const save = useCallback(
    async (next: string) => {
      setIsSaving(true);
      setHasUnsavedChanges(false);
      const trimmed = next.trim();
      try {
        // PATCH only the field this surface owns; the backend merges it into the
        // stored preferences without touching profession/response_style.
        const response = await authApi.updateOnboardingPreferences({
          custom_instructions: trimmed === "" ? null : next,
        });
        if (!response.success) throw new Error(response.message);
        updateUser(
          mergedOnboardingUpdate(user.onboarding, {
            custom_instructions: trimmed === "" ? undefined : next,
          }),
        );
        toast.success("Instructions saved");
      } catch {
        setHasUnsavedChanges(true);
        toast.error("Failed to save instructions");
      } finally {
        setIsSaving(false);
      }
    },
    [user.onboarding, updateUser],
  );

  const onChange = useCallback(
    (next: string) => {
      setValue(next);
      setHasUnsavedChanges(true);
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
      saveTimeoutRef.current = setTimeout(() => save(next), SAVE_DEBOUNCE_MS);
    },
    [save],
  );

  return { value, onChange, isSaving, hasUnsavedChanges };
};
