"use client";

import { Input, Label, Link, Modal, TextField } from "@heroui/react";
import { ArrowRight02Icon } from "@icons";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { FormError } from "@/components/shared/FormError";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { SecretInput } from "@/components/shared/SecretInput";
import { toneVariants } from "@/components/shared/tone";
import CopyButton from "@/components/ui/CopyButton";
import { authApi, getLocalAuthError } from "@/features/auth/api/authApi";

const INVALID_CREDENTIALS_COPY = "Invalid email or password.";
const GENERIC_ERROR_COPY = "Could not sign you in right now. Please try again.";
const RESET_CMD =
  "docker compose -p gaia-selfhost exec gaia-backend python -m app.scripts.reset_admin_password";

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
      <TextField
        className={fieldVariants({ labelPlacement: "inside" })}
        value={email}
        onChange={setEmail}
        isRequired
        isDisabled={isSubmitting}
      >
        <Label>Email</Label>
        <Input
          type="email"
          placeholder="you@example.com"
          autoComplete="email"
        />
      </TextField>
      <SecretInput
        subject="password"
        label="Password"
        value={password}
        onValueChange={setPassword}
        autoComplete="current-password"
        isRequired
        isDisabled={isSubmitting}
      />
      {/* Self-host has one admin and no email recovery — surface the CLI reset path. This form only renders on local-auth instances (see login/page.tsx). */}
      <div className="flex justify-end">
        <GaiaButton
          shape="pill"
          variant="ghost"
          size="sm"
          onPress={() => setShowResetHelp(true)}
          tone="muted"
          className="text-xs"
        >
          Forgot password?
          <ArrowRight02Icon size={14} />
        </GaiaButton>
      </div>

      {error && <FormError>{error}</FormError>}

      <GaiaButton
        type="submit"
        variant="primary"
        isPending={isSubmitting}
        className="w-full"
      >
        Sign in
      </GaiaButton>

      {/* This form only renders on self-host instances (local auth), where a
          signup page exists — mirror the signup page's sign-in link. */}
      <Link
        href="/signup"
        className={toneVariants({
          tone: "accent",
          className: "self-center text-sm hover:underline",
        })}
      >
        Need an account? Sign up
      </Link>

      <Modal
        isOpen={showResetHelp}
        onOpenChange={(open) => setShowResetHelp(open)}
      >
        <Modal.Backdrop>
          <Modal.Container placement="center" size="md">
            <Modal.Dialog>
              <Modal.CloseTrigger aria-label="Close" />
              <Modal.Header>
                <Modal.Heading>Reset admin password</Modal.Heading>
              </Modal.Header>
              <Modal.Body>
                <div className="flex flex-col gap-3 pb-4">
                  <p className="text-sm text-zinc-600 dark:text-zinc-300">
                    If you are the admin and forgot your password, run this on
                    the host that runs GAIA:
                  </p>
                  <div className="relative">
                    <pre className="overflow-x-auto rounded-xl bg-zinc-900 p-3 pr-11 text-xs text-zinc-100">
                      {RESET_CMD}
                    </pre>
                    <CopyButton
                      textToCopy={RESET_CMD}
                      variant="ghost"
                      size="sm"
                      className="absolute top-2 right-2 text-zinc-400"
                    />
                  </div>
                  <p className="text-xs text-zinc-500">
                    It prints a new password for the admin account and signs out
                    every admin session. Sign in with it, then change it in
                    Settings. Your account and data stay as they are.
                  </p>
                </div>
              </Modal.Body>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </form>
  );
}
