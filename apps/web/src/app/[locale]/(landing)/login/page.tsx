import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import { resolveInstanceAuthMode } from "@/features/auth/api/serverSetupStatusApi";
import { AuthShell } from "@/features/auth/components/AuthShell";
import { LoginForm } from "@/features/auth/components/LoginForm";
import {
  oauthLoginUrl,
  safeReturnPath,
} from "@/features/auth/hooks/handleAuthLogin";
import { generatePageMetadata } from "@/lib/seo";

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
  // Self-host instances run local email/password auth; everything else keeps
  // the classic WorkOS OAuth redirect.
  const authMode = await resolveInstanceAuthMode();
  if (authMode === "local") {
    return (
      <AuthShell
        title="Welcome back"
        subtitle="Sign in to your self-hosted GAIA instance."
      >
        <LoginForm safeReturnUrl={safeReturnPath(returnUrl)} />
      </AuthShell>
    );
  }

  return (
    <div className="h-screen">
      <RedirectLoader url={oauthLoginUrl(returnUrl)} replace />
    </div>
  );
}
