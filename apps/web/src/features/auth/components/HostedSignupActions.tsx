"use client";

import Link from "next/link";

import { LinkButton } from "@/components/shared/LinkButton";
import { apiBaseUrl } from "@/lib/api/client";

/** The hosted sign-up page's actions: WorkOS on its sign-up screen, or on sign-in as the navbar opens it. */
export function HostedSignupActions() {
  return (
    <>
      <LinkButton
        href={`${apiBaseUrl}/oauth/login/workos?screen_hint=sign-up`}
        variant="primary"
        shape="pill"
        fullWidth
      >
        Sign up
      </LinkButton>
      <p className="mt-4 text-center text-sm text-zinc-400">
        Already have an account?{" "}
        <Link
          href={`${apiBaseUrl}/oauth/login/workos`}
          className="text-primary"
        >
          Sign in
        </Link>
      </p>
    </>
  );
}
