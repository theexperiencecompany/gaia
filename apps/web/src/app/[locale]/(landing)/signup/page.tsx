import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import { resolveInstanceAuthMode } from "@/features/auth/api/serverSetupStatusApi";
import { AuthShell } from "@/features/auth/components/AuthShell";
import { SignupForm } from "@/features/auth/components/SignupForm";
import { apiauth } from "@/lib/api/client";
import { generatePageMetadata } from "@/lib/seo";

// Mode-switching depends on live instance state (setup/status):
// this page can never be prerendered at build time.
export const dynamic = "force-dynamic";

export const metadata: Metadata = generatePageMetadata({
  title: "Sign Up",
  description:
    "Create your free GAIA account. Get started with your personal AI assistant to automate tasks, manage workflows, and boost productivity today.",
  path: "/signup",
  keywords: [
    "GAIA Sign Up",
    "Create Account",
    "Register",
    "Free AI Assistant",
    "Get Started",
  ],
  noIndex: true,
});

// Self-host instances run local email/password auth; everything else keeps
// the classic WorkOS OAuth redirect.
export default async function SignupPage() {
  const authMode = await resolveInstanceAuthMode();
  if (authMode === "local") {
    return (
      <AuthShell
        title="Create your account"
        subtitle="Set up the administrator account for this GAIA instance."
      >
        <SignupForm />
      </AuthShell>
    );
  }

  return (
    <div className="h-screen">
      <RedirectLoader url={`${apiauth.getUri()}oauth/login/workos`} replace />
    </div>
  );
}
