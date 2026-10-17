"use client";

import { Spinner } from "@heroui/spinner";
import { useInviteLanding } from "../hooks/useInviteLanding";
import { InviteLanding } from "./InviteLanding";

const SIGNUP_HREF = "/signup";

interface InviteLandingPageProps {
  code: string;
}

/** /invite/[code]: resolves in the browser (which arms attribution), then shows the gift. */
export function InviteLandingPage({ code }: InviteLandingPageProps) {
  const { variant, invite, isError } = useInviteLanding(code);

  if (!variant || (!invite && !isError)) {
    return (
      <main className="flex min-h-dvh w-full items-center justify-center bg-primary-bg">
        <Spinner />
      </main>
    );
  }
  return (
    <InviteLanding
      invite={invite ?? null}
      copyVariant={variant}
      signupHref={SIGNUP_HREF}
    />
  );
}
