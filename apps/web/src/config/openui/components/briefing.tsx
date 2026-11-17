import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import type { z } from "zod";

import {
  BriefingFold,
  FoldedBriefCard,
  payloadBrief,
} from "@/features/briefing";

import { briefingSchema } from "../promptSpecs";

// OpenUI props share the payload's shape, so the folded brief opens them as-is
// (no rendered edition image on this path).

function BriefingView(props: z.infer<typeof briefingSchema>) {
  const brief = payloadBrief(props);
  return (
    <div className="w-full max-w-56">
      <BriefingFold brief={brief} payload={props}>
        {(trigger) => <FoldedBriefCard brief={brief} trigger={trigger} />}
      </BriefingFold>
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
