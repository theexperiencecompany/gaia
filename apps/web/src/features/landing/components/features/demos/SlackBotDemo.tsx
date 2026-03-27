"use client";

import { SlackDemoBase } from "@/features/landing/components/demo/SlackDemoBase";

export default function SlackBotDemo() {
  const phase1Content = (
    <div className="space-y-1">
      <p className="text-sm text-zinc-300">
        It&apos;s Monday morning. I can post the weekly metrics summary to{" "}
        <span className="font-semibold text-zinc-100">#general</span>. Want me
        to go ahead?
      </p>
    </div>
  );

  const phase3Response = (
    <div className="space-y-3">
      <p className="text-sm text-zinc-300">
        Here&apos;s your weekly metrics summary:
      </p>
      <div className="rounded-2xl bg-zinc-800 p-4">
        <p className="mb-3 text-sm font-semibold text-zinc-100">
          Weekly Metrics — Mar 17–23
        </p>
        <div className="space-y-2">
          <div className="flex items-center justify-between rounded-xl bg-zinc-900 p-3">
            <span className="text-xs text-zinc-400">Active Users</span>
            <span className="text-xs font-semibold text-emerald-400">
              +12% &nbsp;4,821
            </span>
          </div>
          <div className="flex items-center justify-between rounded-xl bg-zinc-900 p-3">
            <span className="text-xs text-zinc-400">Revenue</span>
            <span className="text-xs font-semibold text-emerald-400">
              +8% &nbsp;$34,200
            </span>
          </div>
          <div className="flex items-center justify-between rounded-xl bg-zinc-900 p-3">
            <span className="text-xs text-zinc-400">Churn Rate</span>
            <span className="text-xs font-semibold text-amber-400">
              2.1% &nbsp;-0.3pp
            </span>
          </div>
          <div className="flex items-center justify-between rounded-xl bg-zinc-900 p-3">
            <span className="text-xs text-zinc-400">Support Tickets</span>
            <span className="text-xs font-semibold text-zinc-300">
              142 resolved
            </span>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <SlackDemoBase
      channel="general"
      phase1Content={phase1Content}
      phase1Time="9:01 AM"
      phase2Time="9:02 AM"
      phase2Question="post our weekly metrics summary to this channel"
      phase3Time="9:02 AM"
      phase3Response={phase3Response}
    />
  );
}
