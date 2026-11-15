"use client";

import { ApiError } from "@shared/api";
import type {
  PlanType,
  ReferralMeResponse,
  ReferralWeeklyCardResponse,
  URLResponse,
  UserSubscriptionStatus,
} from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks/useCurrentUser";
import { fixtureUser } from "./fixtures";

export interface FixtureAccount {
  plan: PlanType;
  me: ReferralMeResponse;
  sentWithGaia: boolean;
  weekly: ReferralWeeklyCardResponse;
  contacts?: URLResponse[];
}

const NOT_SUBSCRIBED = new ApiError(
  "Subscribe to GAIA to get your invite link",
  403,
  {
    envelope: {
      message: "Subscribe to GAIA to get your invite link",
      code: "REFERRAL_SUBSCRIPTION_REQUIRED",
    },
  },
);

const subscription = (plan: PlanType): UserSubscriptionStatus => ({
  user_id: "6650f0c2a1b2c3d4e5f60718",
  plan_type: plan,
  is_subscribed: plan === "pro",
  has_subscription: plan === "pro",
  has_ever_subscribed: plan === "pro",
  status: plan === "pro" ? "active" : null,
  current_plan: null,
  subscription: null,
  days_remaining: null,
  can_upgrade: plan === "free",
  can_downgrade: plan === "pro",
});

/**
 * Every query the real referral components read, answered from fixtures.
 * Defaults carry initialData, so any key under a prefix (a chat turn, the
 * current local week) resolves without the gallery re-deriving it, and
 * nothing is fetched while the page stays open.
 */
function fixtureClient(account: FixtureAccount): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Number.POSITIVE_INFINITY,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        retry: false,
        retryOnMount: false,
      },
    },
  });
  const answer = (queryKey: readonly unknown[], data: unknown) =>
    client.setQueryDefaults(queryKey, { initialData: data });

  answer(CURRENT_USER_QUERY_KEY, fixtureUser(account.sentWithGaia));
  answer(["subscription-status"], subscription(account.plan));
  if (account.plan === "pro") {
    answer(["referrals", "me"], account.me);
  } else {
    // What the server answers a free user, so the page shows its subscribe-first state.
    client
      .getQueryCache()
      .build(client, { queryKey: ["referrals", "me"] })
      .setState({
        status: "error",
        fetchStatus: "idle",
        error: NOT_SUBSCRIBED,
      });
  }
  answer(["referrals", "weekly-card"], account.weekly);
  answer(["referrals", "chat-card"], { show: true });
  for (const contact of account.contacts ?? []) {
    client.setQueryData(["url-metadata", contact.url], contact);
  }
  return client;
}

/** Real components under their own seeded cache; remount (change `key`) to re-seed. */
export function FixtureQueries({
  account,
  children,
}: {
  account: FixtureAccount;
  children: ReactNode;
}) {
  const [client] = useState(() => fixtureClient(account));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
