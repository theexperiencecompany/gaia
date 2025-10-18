import type { Metadata } from "next";

import { RedirectLoader } from "@/components/shared/RedirectLoader";
import { apiauth } from "@/lib";
import { generatePageMetadata } from "@/lib/seo";
// import SignupForm from "@/features/auth/components/SignupForm";

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
});

// Redirect to the OAuth signup endpoint directly
export default function SignupPage() {
  // return <SignupForm />;

  return (
    <div className="h-screen">
      <RedirectLoader url={`${apiauth.getUri()}oauth/login/workos`} replace />
    </div>
  );
}
