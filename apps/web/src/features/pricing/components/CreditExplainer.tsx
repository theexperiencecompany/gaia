"use client";

import { Button } from "@heroui/button";
import { useState } from "react";
import { UsageCatalogModal } from "@/features/settings/components/UsageCatalogModal";

const TIERS: { label: string; credits: string }[] = [
  { label: "Free", credits: "7,500" },
  { label: "Pro", credits: "200,000" },
  { label: "Max", credits: "1,000,000" },
];

/** Pricing-page transparency: per-tier credits + a link to the full breakdown. */
export function CreditExplainer() {
  const [open, setOpen] = useState(false);

  return (
    <div className="mb-20 flex w-full max-w-2xl flex-col items-center gap-7 px-4 text-center">
      <div className="flex flex-col gap-3">
        <h3 className="font-serif text-4xl font-normal text-white">
          You only pay for what you use.
        </h3>
        <p className="text-lg text-zinc-400">
          Every plan comes with monthly credits. A typical message is a few
          credits, and 10,000 credits is $1 of AI compute.
        </p>
      </div>

      <div className="grid w-full grid-cols-3 gap-3">
        {TIERS.map((t) => (
          <div
            key={t.label}
            className="rounded-2xl bg-zinc-900/50 p-5 backdrop-blur-sm"
          >
            <p className="text-sm text-zinc-400">{t.label}</p>
            <p className="mt-1 text-2xl font-semibold text-white">
              {t.credits}
            </p>
            <p className="text-xs text-zinc-500">credits / month</p>
          </div>
        ))}
      </div>

      <Button variant="flat" radius="full" onPress={() => setOpen(true)}>
        See exactly what uses credits
      </Button>

      <UsageCatalogModal isOpen={open} onClose={() => setOpen(false)} />
    </div>
  );
}
