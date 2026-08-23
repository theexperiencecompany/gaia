import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import { getSetupStatusServer } from "@/features/auth/api/serverSetupStatusApi";
import { AuthShell } from "@/features/auth/components/AuthShell";
import { LoginForm } from "@/features/auth/components/LoginForm";
import { apiauth } from "@/lib/api/client";
import { generatePageMetadata } from "@/lib/seo";

// Mode-switching depends on live instance state (setup/status):
// this page can never be prerendered at build time.
export const dynamic = "force-dynamic";

export const metadata: Metadata = generatePageMetadata({
  title: "Login",
  description:
    "Sign in to your GAIA account. Access your personal AI assistant to manage tasks, emails, calendar, goals, and boost your productivity.",
  path: "/login",
  keywords: ["GAIA Login", "Sign In", "Account Access", "User Login"],
  noIndex: true,
});

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ return_url?: string }>;
}) {
  const { return_url: returnUrl } = await searchParams;
  // Only accept relative paths starting with `/` and a non-slash, non-backslash
  // character. Rejects `//evil.com` and `/\evil.com` (browsers normalize `\`
  // to `/`, making the latter protocol-relative).
  const safeReturnUrl =
    returnUrl && /^\/[^/\\]/.test(returnUrl) ? returnUrl : undefined;

  // Self-host instances run local email/password auth; everything else keeps
  // the classic WorkOS OAuth redirect.
  // Self-host sets AUTH_MODE on the container — env-first avoids any
  // dependency on a runtime cross-container fetch for a value that is
  // static per instance. Hosted (no env) falls back to the live probe.
  const envAuthMode = process.env.AUTH_MODE as "workos" | "local" | undefined;
  const setupStatus = envAuthMode
    ? { auth_mode: envAuthMode }
    : await getSetupStatusServer();
  if (setupStatus?.auth_mode === "local") {
    return (
      <AuthShell
        title="Welcome back"
        subtitle="Sign in to your self-hosted GAIA instance."
      >
        <LoginForm safeReturnUrl={safeReturnUrl} />
      </AuthShell>
    );
  }

  const oauthUrl = `${apiauth.getUri()}oauth/login/workos${safeReturnUrl ? `?return_url=${encodeURIComponent(safeReturnUrl)}` : ""}`;

  return (
    <div className="h-screen">
      <RedirectLoader url={oauthUrl} replace />
    </div>
  );
}
