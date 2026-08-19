import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { timelineSchema } from "../promptSpecs";
import { TimelineView } from "./timeline";

export const timelineDef = defineComponent({
  name: "Timeline",
  description:
    "Chronological event feed with timestamps, status dots, optional actor, links, and actions.",
  props: timelineSchema,
  component: ({ props }) => React.createElement(TimelineView, props),
});
