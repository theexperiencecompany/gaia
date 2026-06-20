"use client";

import { Building06Icon, Tick02Icon } from "@icons";
import { useRouter } from "next/navigation";
import { RaisedButton } from "@/components/ui/raised-button";

import type { Plan } from "../api/pricingApi";

interface EnterpriseBarProps {
  plan: Plan;
  ctaHref: string;
}

export function EnterpriseBar({ plan, ctaHref }: EnterpriseBarProps) {
  const router = useRouter();

  return (
    <div className="flex w-full flex-col gap-5 rounded-3xl bg-zinc-800/50 p-6 backdrop-blur-lg sm:flex-row sm:items-center sm:justify-between sm:p-7">
      <div className="flex items-start gap-4">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-primary/10">
          <Building06Icon width={22} height={22} className="text-primary" />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-xl font-semibold">Enterprise</span>
          {plan.description && (
            <p className="text-sm font-light text-zinc-400">
              {plan.description}
            </p>
          )}
          <div className="mt-1 grid grid-cols-1 gap-x-5 gap-y-1.5 sm:grid-cols-[auto_auto]">
            {plan.features.map((feature) => (
              <span
                key={feature}
                className="flex items-center gap-1.5 text-xs font-light text-zinc-400"
              >
                <Tick02Icon width={13} height={13} className="text-primary" />
                {feature}
              </span>
            ))}
          </div>
        </div>
      </div>

      <RaisedButton
        className="shrink-0 text-black!"
        color="#00bbff"
        onClick={() => router.push(ctaHref)}
      >
        Talk to the team
      </RaisedButton>
    </div>
  );
}
