import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import { getSetupStatusServer } from "@/features/auth/api/serverSetupStatusApi";
import { AuthShell } from "@/features/auth/components/AuthShell";
import { RegistrationClosedNotice } from "@/features/auth/components/RegistrationClosedNotice";
import { SignupForm } from "@/features/auth/components/SignupForm";
import {
  resolveSignupMode,
  type SignupMode,
} from "@/features/auth/utils/signupMode";
import { apiBaseUrl } from "@/lib/api/client";
import { isSelfhostWeb } from "@/lib/selfhost";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Sign Up",
  description:
    "Create your GAIA account. Get started with your personal AI assistant to automate tasks, manage workflows, and boost productivity today.",
  path: "/signup",
  keywords: ["GAIA Sign Up", "Create Account", "Register", "Get Started"],
  noIndex: true,
});

const LOCAL_SIGNUP_SUBTITLES: Record<SignupMode, string> = {
  first_account: "Set up the administrator account for this GAIA instance.",
  member: "Join this GAIA instance.",
  closed: "This GAIA instance is invite only.",
};

interface SignupPageProps {
  searchParams: Promise<{ invite?: string }>;
}

// Self-host instances run local email/password auth; everything else keeps
// the classic WorkOS OAuth redirect.
export default async function SignupPage({ searchParams }: SignupPageProps) {
  const status = isSelfhostWeb() ? await getSetupStatusServer() : null;
  if (status?.auth_mode === "local") {
    const { invite } = await searchParams;
    const mode = resolveSignupMode(status, invite);
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
