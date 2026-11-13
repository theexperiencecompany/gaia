"use client";

import { Button } from "@heroui/button";
import Link from "next/link";

import { apiBaseUrl } from "@/lib/api/client";

/** The hosted sign-up page's actions: WorkOS on its sign-up screen, or on sign-in as the navbar opens it. */
export function HostedSignupActions() {
  return (
    <>
      <Button
        as={Link}
        href={`${apiBaseUrl}/oauth/login/workos?screen_hint=sign-up`}
        color="primary"
        radius="full"
        fullWidth
      >
        Sign up
      </Button>
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
