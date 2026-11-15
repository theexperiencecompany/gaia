"use client";

import { Button } from "@heroui/button";
import Link from "next/link";

import { StandalonePage } from "@/components/layout/StandalonePage";
import { useLogout } from "@/features/auth/hooks/useLogout";
import { loginHref } from "@/features/auth/utils/loginHref";

import {
  DEAD_LINK_COPY,
  FORBIDDEN_COPY,
  SIGN_IN_REQUIRED_COPY,
} from "../constants";
import type { LinkUnavailableState } from "../types";

function linkPath(slug: string): string {
  return `/l/${slug}`;
}

/** Sign out of the account that may not open the link, then sign in again and come back to it. */
function SwitchAccountButton({ slug }: { slug: string }) {
  const { logout } = useLogout();
  return (
    <Button variant="flat" onPress={() => logout(linkPath(slug))}>
      Sign in with another account
    </Button>
  );
}

function Message({ state }: { state: LinkUnavailableState }) {
  if (state.denial === "link_sign_in_required") {
    return (
      <>
        <h1 className="text-2xl font-medium text-balance text-white">
          {SIGN_IN_REQUIRED_COPY}
        </h1>
        <Button
          as={Link}
          href={loginHref(linkPath(state.slug))}
          color="primary"
          className="mt-3"
        >
          Sign in
        </Button>
      </>
    );
  }
  if (state.denial === "link_forbidden") {
    return (
      <>
        <h1 className="text-2xl font-medium text-balance text-white">
          {FORBIDDEN_COPY}
        </h1>
        <p className="max-w-sm text-sm text-pretty text-zinc-400">
          You're signed in as {state.signedInAs}.
        </p>
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          <SwitchAccountButton slug={state.slug} />
          <Button as={Link} href="/" color="primary">
            Go to GAIA
          </Button>
        </div>
      </>
    );
  }
  return (
    <>
      <h1 className="text-2xl font-medium text-balance text-white">
        {DEAD_LINK_COPY[state.denial]}
      </h1>
      <Button as={Link} href="/" color="primary" className="mt-3">
        Go to GAIA
      </Button>
    </>
  );
}

/** What a heygaia.link opens to when it doesn't open: dead, or not for this viewer. Never says what it pointed at. */
export function LinkUnavailable({ state }: { state: LinkUnavailableState }) {
  return (
    <StandalonePage>
      <section className="flex flex-col items-center gap-3 py-24 text-center">
        <Message state={state} />
      </section>
    </StandalonePage>
  );
}
