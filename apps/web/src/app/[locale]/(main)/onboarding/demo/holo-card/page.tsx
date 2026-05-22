"use client";

import { Select, SelectItem } from "@heroui/select";
import { notFound } from "next/navigation";
import { useState } from "react";
import type { HoloCardDisplayData } from "@/components/ui/holo-card/types";
import { HoloCardReveal } from "@/features/onboarding/components/reveal/HoloCardReveal";
import type { PersonalizationData } from "@/features/onboarding/types/websocket";

if (process.env.NODE_ENV === "production") {
  notFound();
}

const HOLO_CARD_VARIANTS: HoloCardDisplayData[] = [
  {
    house: "frostpeak",
    name: "Aryan",
    personality_phrase: "Glacier Strategist",
    user_bio:
      "Calm under pressure, sharp at the summit. Plans three moves ahead and never rushes the descent.",
    account_number: 1247,
    member_since: "April 2025",
    overlay_color: "rgba(125, 211, 252, 0.15)",
    overlay_opacity: 40,
  },
  {
    house: "greenvale",
    name: "Aryan",
    personality_phrase: "Verdant Builder",
    user_bio:
      "Grows ideas like gardens — patient, deliberate, and quietly relentless until everything blooms.",
    account_number: 1247,
    member_since: "April 2025",
    overlay_color: "rgba(74, 222, 128, 0.15)",
    overlay_opacity: 40,
  },
  {
    house: "mistgrove",
    name: "Aryan",
    personality_phrase: "Mist Wanderer",
    user_bio:
      "Drawn to the unknown, comfortable in ambiguity. Finds the path others miss in the fog.",
    account_number: 1247,
    member_since: "April 2025",
    overlay_color: "rgba(167, 139, 250, 0.15)",
    overlay_opacity: 40,
  },
  {
    house: "bluehaven",
    name: "Aryan",
    personality_phrase: "Midnight Architect",
    user_bio:
      "Ships code like it owes him money — fast, opinionated, and somehow always elegant.",
    account_number: 1247,
    member_since: "April 2025",
    overlay_color: "rgba(59, 130, 246, 0.15)",
    overlay_opacity: 40,
  },
];

function variantToPersonalization(
  variant: HoloCardDisplayData,
): PersonalizationData {
  return {
    house: variant.house,
    name: variant.name,
    personality_phrase: variant.personality_phrase,
    user_bio: variant.user_bio,
    account_number:
      typeof variant.account_number === "number"
        ? variant.account_number
        : undefined,
    member_since: variant.member_since,
    overlay_color: variant.overlay_color,
    overlay_opacity: variant.overlay_opacity,
    holo_card_id: variant.holo_card_id,
  };
}

export default function HoloCardDemoPage() {
  const [house, setHouse] = useState<string>(HOLO_CARD_VARIANTS[0].house);
  const variant =
    HOLO_CARD_VARIANTS.find((v) => v.house === house) ?? HOLO_CARD_VARIANTS[0];

  return (
    <div className="relative flex h-full items-center justify-center bg-primary-bg px-6">
      <div className="absolute top-6 left-1/2 -translate-x-1/2">
        <Select
          aria-label="House"
          selectedKeys={[house]}
          onSelectionChange={(keys) => {
            const next = Array.from(keys)[0];
            if (next) setHouse(String(next));
          }}
          className="w-48"
        >
          {HOLO_CARD_VARIANTS.map((v) => (
            <SelectItem key={v.house}>{v.house}</SelectItem>
          ))}
        </Select>
      </div>
      <HoloCardReveal personalizationData={variantToPersonalization(variant)} />
    </div>
  );
}
