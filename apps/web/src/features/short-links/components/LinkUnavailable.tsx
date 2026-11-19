"use client";

import { StandalonePage } from "@/components/layout/StandalonePage";
import { LinkButton } from "@/components/shared/LinkButton";

/** What a heygaia.link that is stopped, expired or unknown opens to. */
export function LinkUnavailable() {
  return (
    <StandalonePage>
      <section className="flex flex-col items-center gap-3 py-24 text-center">
        <h1 className="text-2xl font-medium text-balance text-white">
          This link isn't available
        </h1>
        <p className="max-w-sm text-sm text-pretty text-zinc-400">
          The person who shared it may have turned it off.
        </p>
        <LinkButton href="/" variant="primary" className="mt-3">
          Go to GAIA
        </LinkButton>
      </section>
    </StandalonePage>
  );
}
