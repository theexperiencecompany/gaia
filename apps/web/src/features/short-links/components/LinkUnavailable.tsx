"use client";

import { Button } from "@heroui/button";
import Link from "next/link";

import { StandalonePage } from "@/components/layout/StandalonePage";

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
        <Button as={Link} href="/" color="primary" className="mt-3">
          Go to GAIA
        </Button>
      </section>
    </StandalonePage>
  );
}
