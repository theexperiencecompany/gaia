"use client";

import { Spinner } from "@heroui/spinner";
import { useInviteLanding } from "../hooks/useInviteLanding";
import { InviteAlreadyOnGaia, InviteLanding } from "./InviteLanding";

const SIGNUP_HREF = "/signup";

interface InviteLandingPageProps {
  code: string;
}

/** /invite/[code]: a member goes back to their chat; anyone else resolves in the browser (arming attribution) and sees the gift. */
export function InviteLandingPage({ code }: InviteLandingPageProps) {
  const { variant, isSignedIn, invite, isError } = useInviteLanding(code);

  if (isSignedIn) return <InviteAlreadyOnGaia />;

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
