"use client";

import { Button } from "@heroui/button";

/** What skipping provider setup means, with the way back to it later. */
export function SkipProviderNotice({ onNext }: { onNext?: () => void }) {
  return (
    <div className="w-full rounded-2xl bg-zinc-800 p-4">
      <p className="text-sm font-medium text-zinc-100">
        Skip provider setup for now
      </p>
      <p className="mt-1 text-sm leading-relaxed text-zinc-400">
        You can add a provider later in{" "}
        <span className="font-medium text-zinc-300">
          Settings, under Providers &amp; Tools
        </span>
        . Without a provider, chat can&apos;t reply yet.
      </p>
      {onNext && (
        <Button
          size="sm"
          color="primary"
          variant="flat"
          className="mt-3"
          onPress={onNext}
        >
          Continue without a provider
        </Button>
      )}
    </div>
  );
}
