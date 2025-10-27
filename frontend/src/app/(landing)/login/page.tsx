import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import { apiauth } from "@/lib";
import { generatePageMetadata } from "@/lib/seo";

// import LoginForm from "@/features/auth/components/LoginForm";

export const metadata: Metadata = generatePageMetadata({
  title: "Login",
  description:
    "Sign in to your GAIA account. Access your personal AI assistant to manage tasks, emails, calendar, goals, and boost your productivity.",
  path: "/login",
  keywords: ["GAIA Login", "Sign In", "Account Access", "User Login"],
});

// Redirect to the OAuth login endpoint directly
export default function LoginPage() {
  // return <LoginForm />;

  return (
    <div className="h-screen">
      <RedirectLoader url={`${apiauth.getUri()}oauth/login/workos`} replace />
    </div>
  );
}
