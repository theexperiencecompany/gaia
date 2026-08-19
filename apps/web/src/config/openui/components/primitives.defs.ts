import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { avatarSchema, progressSchema } from "../promptSpecs";
import { AvatarView, ProgressView } from "./primitives";

export const progressDef = defineComponent({
  name: "Progress",
  description: "Progress bar with optional label and value display.",
  props: progressSchema,
  component: ({ props }) => React.createElement(ProgressView, props),
});

export const avatarDef = defineComponent({
  name: "Avatar",
  description: "User avatar with name label.",
  props: avatarSchema,
  component: ({ props }) => React.createElement(AvatarView, props),
});
