import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import type { z } from "zod";

import { BriefingFold } from "@/features/briefing";

import { briefingSchema } from "../promptSpecs";

// OpenUI props share the payload's shape, so the folded brief opens them as-is
// (no rendered edition image on this path).

function BriefingView(props: z.infer<typeof briefingSchema>) {
  return <BriefingFold headline={props.headline} payload={props} />;
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
