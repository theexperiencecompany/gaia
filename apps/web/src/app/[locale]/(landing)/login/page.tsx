import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import { oauthLoginUrl } from "@/features/auth/hooks/handleAuthLogin";
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

  return (
    <div className="h-screen">
      <RedirectLoader url={oauthLoginUrl(returnUrl)} replace />
    </div>
  );
}
