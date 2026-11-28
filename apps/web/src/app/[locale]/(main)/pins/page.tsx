import type { Metadata } from "next";

import { EffectPinsBranch } from "@/components/effect/EffectPinsBranch";
import Pins from "@/features/pins/components/PinsPage";
import { EFFECT_UI_ENABLED } from "@/config/effectUi";

export const metadata: Metadata = {
  title: "Pinned Messages",
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1/";

export default async function Page({
  searchParams,
}: Readonly<{
  searchParams: Promise<{ effect?: string }>;
}>) {
  const { effect } = await searchParams;

  if (effect === "1" && EFFECT_UI_ENABLED) {
    return <EffectPinsBranch apiBaseUrl={API_BASE_URL} />;
  }

  return <Pins />;
}
