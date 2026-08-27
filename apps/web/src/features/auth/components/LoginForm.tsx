"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Link } from "@heroui/link";
import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/modal";
import { Alert01Icon, ArrowRight02Icon } from "@icons";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { authApi, getLocalAuthError } from "@/features/auth/api/authApi";

const INVALID_CREDENTIALS_COPY = "Invalid email or password.";
const GENERIC_ERROR_COPY = "Could not sign you in right now. Please try again.";
const RESET_CMD =
  "docker compose -p gaia-selfhost exec gaia-backend python -m app.scripts.reset_admin_password";
const RESET_MONGO_CMD =
  "docker compose -p gaia-selfhost exec mongo mongosh --eval 'db.getSiblingDB(\"gaia\").auth_credentials.deleteMany({})'";

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
  const [showResetHelp, setShowResetHelp] = useState(false);

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
      {/* Self-host has one admin and no email recovery — surface the CLI reset path. This form only renders on local-auth instances (see login/page.tsx). */}
      <div className="flex justify-end">
        <Button
          variant="light"
          size="sm"
          radius="full"
          endContent={<ArrowRight02Icon size={14} />}
          onPress={() => setShowResetHelp(true)}
          className="text-xs text-zinc-400"
        >
          Forgot password?
        </Button>
      </div>

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

      <Modal
        isOpen={showResetHelp}
        onClose={() => setShowResetHelp(false)}
        size="md"
      >
        <ModalContent>
          <ModalHeader>Reset admin password</ModalHeader>
          <ModalBody className="gap-3 pb-6">
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              Self-hosted GAIA has one admin account. To reset your password,
              run this on the host that runs GAIA:
            </p>
            <pre className="overflow-x-auto rounded-xl bg-zinc-900 p-3 text-xs text-zinc-100">
              {RESET_CMD}
            </pre>
            <p className="text-xs text-zinc-500">
              Then open{" "}
              <Link href="/signup" size="sm" color="primary">
                /signup
              </Link>{" "}
              to create a new admin account. Alternative (direct Mongo):
            </p>
            <pre className="overflow-x-auto rounded-xl bg-zinc-900 p-3 text-xs text-zinc-100">
              {RESET_MONGO_CMD}
            </pre>
          </ModalBody>
        </ModalContent>
      </Modal>
    </form>
  );
}
