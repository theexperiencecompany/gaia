import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import type { z } from "zod";

import { BriefingCard } from "@/features/briefing/components/BriefingCard";

import { briefingSchema } from "../promptSpecs";

// The editorial rendering lives in exactly one place — `BriefingCard` in the
// `briefing` feature module — so the dashboard and this LLM-emitted path stay
// visually identical. This view is a thin adapter: OpenUI props are the same
// shape as `BriefingPayload`, so they pass straight through.

function BriefingView(props: z.infer<typeof briefingSchema>) {
  return <BriefingCard payload={props} defaultCollapsed={false} />;
}

export const briefingDef = defineComponent({
  name: "Briefing",
  description:
    "Editorial daily/weekly briefing artifact: masthead (kicker + date), hue-rotated hero band, serif " +
    "display headline, lede, a stat row, Roman-numeraled sections of items (optionally linking to a " +
    "todo), and a caption footer. Use only for GAIA's own daily/weekly briefing payloads — never " +
    "hand-assemble one from other components.",
  props: briefingSchema,
  component: ({ props }) => React.createElement(BriefingView, props),
});
