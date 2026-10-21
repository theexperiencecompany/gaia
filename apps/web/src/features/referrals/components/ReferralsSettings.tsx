"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { GiftIcon } from "@icons";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";
import {
  sendReferralInvite,
  useReferralMe,
  useReferralSuggestions,
} from "../hooks/useReferrals";
import { REFERRAL_UI_COPY } from "../referralCopy";
import { ReferralsView } from "./page/layouts";

/** Settings → Referrals: the layout and angle the server picked, with live friends and suggestions. */
export function ReferralsSettings() {
  const state = useReferralMe();
  const { data: suggestions } = useReferralSuggestions(
    state.status === "ready",
  );

  switch (state.status) {
    case "loading":
      return <ReferralsSkeleton />;
    case "subscribe_first":
      return <SubscribeFirst />;
    case "error":
      return <ReferralsError onRetry={state.retry} />;
    case "ready":
      return (
        <ReferralsView
          layout={state.me.layout_variant}
          copyVariant={state.me.copy_variant}
          me={state.me}
          suggestions={suggestions ?? []}
          send={sendReferralInvite}
        />
      );
  }
}

function SubscribeFirst() {
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-3 rounded-3xl bg-zinc-900/60 px-6 py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-zinc-800 text-zinc-300">
        <GiftIcon width={22} height={22} />
      </div>
      <p className="text-base font-medium text-zinc-100">
        {REFERRAL_UI_COPY.subscribeFirstTitle}
      </p>
      <p className="max-w-sm text-sm text-pretty text-zinc-400">
        {REFERRAL_UI_COPY.subscribeFirstBody}
      </p>
      <Button
        color="primary"
        radius="full"
        className="mt-2 font-medium"
        onPress={() =>
          openUpgradeModal(undefined, {
            dismissible: true,
            source: "settings_referrals",
          })
        }
      >
        {REFERRAL_UI_COPY.subscribeFirstCta}
      </Button>
    </div>
  );
}

function ReferralsError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-3 rounded-3xl bg-zinc-900/60 p-10 text-center">
      <p className="text-sm font-medium text-zinc-200">
        {REFERRAL_UI_COPY.loadFailedTitle}
      </p>
      <Button
        size="sm"
        variant="flat"
        radius="full"
        className="font-medium"
        onPress={onRetry}
      >
        {REFERRAL_UI_COPY.tryAgain}
      </Button>
    </div>
  );
}

function ReferralsSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Skeleton className="h-9 w-64 rounded-xl" />
        <Skeleton className="h-4 w-full max-w-md rounded-full" />
      </div>
      <Skeleton className="h-56 w-full rounded-3xl" />
      <Skeleton className="h-11 w-full rounded-full" />
      <Skeleton className="h-40 w-full rounded-2xl" />
    </div>
  );
}
