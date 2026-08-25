"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Alert01Icon } from "@icons";
import { type FormEvent, useState } from "react";

import { authApi, getLocalAuthError } from "@/features/auth/api/authApi";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";

// Mirrors SignupRequest.password's min_length on the backend.
const MIN_PASSWORD_LENGTH = 8;

const WRONG_CURRENT_PASSWORD_COPY = "Current password is incorrect.";
const LENGTH_COPY = `New password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
const MISMATCH_COPY = "New passwords do not match.";

/**
 * Self-service password rotation for local-auth (self-host) accounts, backed
 * by PATCH /auth/password. Rendered only when the instance runs AUTH_MODE
 * "local" — hosted WorkOS identities have no GAIA-local password to rotate.
 */
export function PasswordChangeSection() {
  const { data: setupStatus } = useSetupStatus();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hidden while the setup-status probe is still loading.
  if (setupStatus?.auth_mode !== "local") return null;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting || !currentPassword || !newPassword || !confirmPassword) {
      return;
    }
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setError(LENGTH_COPY);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(MISMATCH_COPY);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await authApi.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      const authError = getLocalAuthError(err);
      if (
        authError.status === 401 &&
        authError.errorCode === API_ERROR_CODES.INVALID_CREDENTIALS
      ) {
        setError(WRONG_CURRENT_PASSWORD_COPY);
      }
      // Every other failure (network, 429, 5xx) is already surfaced by the
      // axios interceptor / apiService toasts — no inline duplicate.
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <SettingsSection
      title="Password"
      description="Update the password you use to sign in to this instance"
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-3 px-4 py-3.5">
        <Input
          type="password"
          label="Current password"
          value={currentPassword}
          onValueChange={setCurrentPassword}
          autoComplete="current-password"
          isRequired
          isDisabled={isSubmitting}
        />
        <Input
          type="password"
          label="New password"
          value={newPassword}
          onValueChange={setNewPassword}
          autoComplete="new-password"
          minLength={MIN_PASSWORD_LENGTH}
          isRequired
          isDisabled={isSubmitting}
        />
        <Input
          type="password"
          label="Confirm new password"
          value={confirmPassword}
          onValueChange={setConfirmPassword}
          autoComplete="new-password"
          isRequired
          isDisabled={isSubmitting}
        />

        {error && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-xl bg-red-400/10 px-3 py-2 text-sm text-red-400"
          >
            <Alert01Icon height={17} className="shrink-0" />
            {error}
          </div>
        )}

        <div>
          <Button
            type="submit"
            color="primary"
            size="sm"
            isLoading={isSubmitting}
          >
            Update password
          </Button>
        </div>
      </form>
    </SettingsSection>
  );
}
