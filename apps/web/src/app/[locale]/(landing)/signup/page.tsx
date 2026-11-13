import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import { getSetupStatusServer } from "@/features/auth/api/serverSetupStatusApi";
import { AuthShell } from "@/features/auth/components/AuthShell";
import { HostedSignupActions } from "@/features/auth/components/HostedSignupActions";
import { RegistrationClosedNotice } from "@/features/auth/components/RegistrationClosedNotice";
import { SignupForm } from "@/features/auth/components/SignupForm";
import {
  resolveSignupMode,
  type SignupMode,
} from "@/features/auth/utils/signupMode";
import { isSelfhostWeb } from "@/lib/selfhost";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

const TITLE = "Sign Up for GAIA: Your Proactive Personal AI Assistant";
const DESCRIPTION =
  "Create your GAIA account and get a proactive AI assistant that handles your email, calendar, tasks and workflows, and acts before you have to ask.";
const PAGE_URL = `${siteConfig.url}/signup`;

export const metadata: Metadata = generatePageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/signup",
  keywords: ["GAIA sign up", "create GAIA account", "AI assistant sign up"],
});

const LOCAL_SIGNUP_SUBTITLES: Record<SignupMode, string> = {
  first_account: "Set up the administrator account for this GAIA instance.",
  member: "Join this GAIA instance.",
  closed: "This GAIA instance is invite only.",
};

interface SignupPageProps {
  searchParams: Promise<{ invite?: string }>;
}

// Self-host instances run local email/password auth; everything else signs up
// through WorkOS from this page.
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

  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: "Sign Up", url: PAGE_URL },
  ];
  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(TITLE, DESCRIPTION, PAGE_URL, breadcrumbs),
          generateBreadcrumbSchema(breadcrumbs),
        ]}
      />
      <AuthShell
        title="Create your GAIA account"
        subtitle="Your proactive AI assistant for email, calendar, tasks and workflows."
      >
        <HostedSignupActions />
      </AuthShell>
    </>
  );
}
