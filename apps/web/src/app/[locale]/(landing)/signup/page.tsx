import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import {
  getSetupStatusServer,
  resolveInstanceAuthMode,
} from "@/features/auth/api/serverSetupStatusApi";
import { AuthShell } from "@/features/auth/components/AuthShell";
import { RegistrationClosedNotice } from "@/features/auth/components/RegistrationClosedNotice";
import { SignupForm } from "@/features/auth/components/SignupForm";
import {
  resolveSignupMode,
  type SignupMode,
} from "@/features/auth/utils/signupMode";
import { apiBaseUrl } from "@/lib/api/client";
import { generatePageMetadata } from "@/lib/seo";

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

const LOCAL_SIGNUP_SUBTITLES: Record<SignupMode, string> = {
  first_account: "Set up the administrator account for this GAIA instance.",
  member: "Join this GAIA instance.",
  closed: "This GAIA instance is invite only.",
  unknown: "Create an account on this GAIA instance.",
};

interface SignupPageProps {
  searchParams: Promise<{ invite?: string }>;
}

// Self-host instances run local email/password auth; everything else keeps
// the classic WorkOS OAuth redirect.
export default async function SignupPage({ searchParams }: SignupPageProps) {
  const authMode = await resolveInstanceAuthMode();
  if (authMode === "local") {
    const { invite } = await searchParams;
    const mode = resolveSignupMode(await getSetupStatusServer(), invite);
    return (
      <AuthShell
        title={
          mode === "closed" ? "Sign-ups are closed" : "Create your account"
        }
        subtitle={LOCAL_SIGNUP_SUBTITLES[mode]}
      >
        {mode === "closed" ? (
          <RegistrationClosedNotice />
        ) : (
          <SignupForm
            invite={invite}
            redirectTo={mode === "first_account" ? "/setup" : "/redirect"}
          />
        )}
      </AuthShell>
    );
  }

  return (
    <div className="h-screen">
      <RedirectLoader url={`${apiBaseUrl}/oauth/login/workos`} replace />
    </div>
  );
}
