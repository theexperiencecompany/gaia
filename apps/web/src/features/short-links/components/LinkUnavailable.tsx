"use client";

import { Button } from "@heroui/button";
import Link from "next/link";

import { StandalonePage } from "@/components/layout/StandalonePage";

import {
  DEAD_LINK_COPY,
  FORBIDDEN_COPY,
  SIGN_IN_REQUIRED_COPY,
} from "../constants";
import type { LinkUnavailableState } from "../types";

/** The sign-in page, returning to the link once the viewer is signed in. */
function signInHref(slug: string): string {
  return `/login?return_url=${encodeURIComponent(`/l/${slug}`)}`;
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
          href={signInHref(state.slug)}
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
        <Button as={Link} href="/" color="primary" className="mt-3">
          Go to GAIA
        </Button>
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
