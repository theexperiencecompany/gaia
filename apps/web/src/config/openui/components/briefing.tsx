import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import type { z } from "zod";

import { BriefingCard } from "@/features/briefing/components/BriefingCard";

import { briefingSchema } from "../promptSpecs";

// BriefingCard is the one editorial rendering; OpenUI props share the
// BriefingPayload shape, so they pass straight through.

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
