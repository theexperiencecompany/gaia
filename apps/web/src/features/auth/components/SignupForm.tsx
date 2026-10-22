"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Alert01Icon } from "@icons";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { SecretInput } from "@/components/shared/SecretInput";

import { authApi, getLocalAuthError } from "@/features/auth/api/authApi";
import { RegistrationClosedNotice } from "@/features/auth/components/RegistrationClosedNotice";
import { MIN_PASSWORD_LENGTH } from "@/features/auth/constants";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";

const INVITE_INVALID_COPY =
  "This invite link was already used or has expired. Ask for a new one.";
const GENERIC_ERROR_COPY = "Could not create your account. Please try again.";

/**
 * Local-mode (self-host) signup. The first account administers the instance
 * and continues into the setup wizard; later accounts are members, admitted by
 * an invite link or by open registration, and land in the app.
 */
interface SignupFormProps {
  /**
   * Called after the account is created instead of navigating — the setup
   * wizard embeds this form as its first step and continues in place.
   */
  onCreated?: () => void;
  /** The token from an invite link, sent with the signup. */
  invite?: string;
  /** Where a new account goes next; the first account goes to /setup. */
  redirectTo?: string;
}

export function SignupForm({
  onCreated,
  invite,
  redirectTo = "/setup",
}: SignupFormProps) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isRegistrationClosed, setIsRegistrationClosed] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) return;
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await authApi.localSignup(name, email.trim(), password, invite);
      if (onCreated) {
        onCreated();
        return;
      }
      router.push(redirectTo);
    } catch (err) {
      const authError = getLocalAuthError(err);
      if (authError.errorCode === API_ERROR_CODES.REGISTRATION_CLOSED) {
        setIsRegistrationClosed(true);
      } else if (authError.errorCode === API_ERROR_CODES.INVITE_INVALID) {
        setError(INVITE_INVALID_COPY);
      } else {
        setError(authError.message ?? GENERIC_ERROR_COPY);
      }
      setIsSubmitting(false);
    }
  }

  if (isRegistrationClosed) {
    return <RegistrationClosedNotice />;
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <Input
        label="Name"
        placeholder="Optional"
        value={name}
        onValueChange={setName}
        autoComplete="name"
        isDisabled={isSubmitting}
        variant="faded"
      />
      <Input
        type="email"
        label="Email"
        placeholder="you@example.com"
        value={email}
        onValueChange={setEmail}
        autoComplete="email"
        isRequired
        isDisabled={isSubmitting}
        variant="faded"
      />
      <SecretInput
        subject="password"
        label="Password"
        value={password}
        onValueChange={setPassword}
        autoComplete="new-password"
        description={`At least ${MIN_PASSWORD_LENGTH} characters`}
        isRequired
        isDisabled={isSubmitting}
        variant="faded"
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

      <Button
        type="submit"
        color="primary"
        isLoading={isSubmitting}
        className="w-full"
      >
        Create account
      </Button>
    </form>
  );
}
