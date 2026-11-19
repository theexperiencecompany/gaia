import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import type { z } from "zod";

import { BriefingFold } from "@/features/briefing";

import { briefingSchema } from "../promptSpecs";

// OpenUI props share the payload's shape, so the folded brief opens them as-is
// (no rendered edition image on this path).

function BriefingView(props: z.infer<typeof briefingSchema>) {
  return (
    <div className="w-full max-w-56">
      <BriefingFold
        brief={{ headline: props.headline, date: props.date, lede: props.lede }}
        payload={props}
      />
    </div>
  );
}

export const briefingDef = defineComponent({
  name: "Briefing",
  description:
    "GAIA's daily/weekly briefing: its headline, the message GAIA wrote, then its sections of items " +
    "(optionally linking to a todo). Use only for GAIA's own daily/weekly briefing payloads — never " +
    "hand-assemble one from other components.",
  props: briefingSchema,
  component: ({ props }) => React.createElement(BriefingView, props),
});
