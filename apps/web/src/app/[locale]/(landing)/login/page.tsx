import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import { apiauth } from "@/lib/api/client";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Login",
  description:
    "Sign in to your GAIA account. Access your personal AI assistant to manage tasks, emails, calendar, goals, and boost your productivity.",
  path: "/login",
  keywords: ["GAIA Login", "Sign In", "Account Access", "User Login"],
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
  const oauthUrl = `${apiauth.getUri()}oauth/login/workos${safeReturnUrl ? `?return_url=${encodeURIComponent(safeReturnUrl)}` : ""}`;

  return (
    <div className="h-screen">
      <RedirectLoader url={oauthUrl} replace />
    </div>
  );
}
