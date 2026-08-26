"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Link } from "@heroui/link";
import { Alert01Icon } from "@icons";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { authApi, getLocalAuthError } from "@/features/auth/api/authApi";

const INVALID_CREDENTIALS_COPY = "Invalid email or password.";
const GENERIC_ERROR_COPY = "Could not sign you in right now. Please try again.";

interface LoginFormProps {
  /**
   * Server-sanitized relative path to return to after login. Falls back to
   * the auth redirect handler when absent.
   */
  safeReturnUrl?: string;
}

export function LoginForm({ safeReturnUrl }: LoginFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting || !email.trim() || !password) return;

    setIsSubmitting(true);
    setError(null);
    try {
      await authApi.localLogin(email.trim(), password);
      // The session cookie is set; the redirect handler picks up the fresh
      // user (or the return path continues where the visitor left off).
      router.push(safeReturnUrl ?? "/redirect");
    } catch (err) {
      const authError = getLocalAuthError(err);
      setError(
        authError.status === 401
          ? INVALID_CREDENTIALS_COPY
          : GENERIC_ERROR_COPY,
      );
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
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
        autoComplete="current-password"
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
        Sign in
      </Button>

      {/* This form only renders on self-host instances (local auth), where a
          signup page exists — mirror the signup page's sign-in link. */}
      <Link href="/signup" size="sm" color="primary" className="self-center">
        Need an account? Sign up
      </Link>
    </form>
  );
}
