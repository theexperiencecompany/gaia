"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Link } from "@heroui/link";
import { Alert01Icon } from "@icons";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { authApi, getLocalAuthError } from "@/features/auth/api/authApi";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";

const MIN_PASSWORD_LENGTH = 8;
const REGISTRATION_CLOSED_COPY =
  "This instance already has an administrator account";
const GENERIC_ERROR_COPY = "Could not create your account. Please try again.";

/**
 * Local-mode (self-host) signup. A GAIA instance has exactly one
 * administrator: the first successful signup creates it and the setup wizard
 * takes over; later signups are refused by the backend with 403
 * `registration_closed`.
 */
interface SignupFormProps {
  /**
   * Called after the admin account is created instead of navigating to
   * /setup — the setup wizard embeds this form as its first step and
   * continues in place.
   */
  onCreated?: () => void;
}

export function SignupForm({ onCreated }: SignupFormProps) {
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
      await authApi.localSignup(name, email.trim(), password);
      // Hand off to the first-run setup wizard (or let the embedding wizard
      // continue in place).
      if (onCreated) {
        onCreated();
        return;
      }
      router.push("/setup");
    } catch (err) {
      const authError = getLocalAuthError(err);
      if (
        authError.status === 403 &&
        authError.errorCode === API_ERROR_CODES.REGISTRATION_CLOSED
      ) {
        setIsRegistrationClosed(true);
      } else {
        setError(authError.message ?? GENERIC_ERROR_COPY);
      }
      setIsSubmitting(false);
    }
  }

  if (isRegistrationClosed) {
    return (
      <div className="flex flex-col items-center gap-4" role="alert">
        <div className="flex items-center gap-2 rounded-xl bg-amber-400/10 px-3 py-2 text-sm text-amber-400">
          <Alert01Icon height={17} className="shrink-0" />
          {REGISTRATION_CLOSED_COPY}
        </div>
        <Link href="/login" size="sm" color="primary">
          Sign in instead
        </Link>
      </div>
    );
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
      />
      <Input
        type="password"
        label="Password"
        value={password}
        onValueChange={setPassword}
        autoComplete="new-password"
        description={`At least ${MIN_PASSWORD_LENGTH} characters`}
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
