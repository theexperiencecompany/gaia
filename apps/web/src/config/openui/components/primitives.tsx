import { Avatar, Progress } from "@heroui/react";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import type { z } from "zod";
import { avatarSchema, progressSchema } from "../promptSpecs";

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

export function ProgressView(props: z.infer<typeof progressSchema>) {
  const max = props.max && props.max > 0 ? props.max : 100;
  const ratio = (props.value ?? 0) / max;
  const pct = Number.isFinite(ratio)
    ? Math.max(0, Math.min(100, Math.round(ratio * 100)))
    : 0;
  return (
    <div className="w-full">
      {(props.label || props.showValue) && (
        <div className="flex justify-between items-center mb-1">
          {props.label && (
            <span className="text-xs text-zinc-400">{props.label}</span>
          )}
          {props.showValue && (
            <span className="text-xs text-zinc-500">{pct}%</span>
          )}
        </div>
      )}
      <Progress
        value={pct}
        color={props.color ?? "primary"}
        size="md"
        classNames={{ track: "bg-zinc-800" }}
      />
    </div>
  );
}

export function AvatarView(props: z.infer<typeof avatarSchema>) {
  return (
    <div className="flex items-center gap-2">
      <Avatar
        name={props.name}
        src={props.image}
        showFallback
        size="sm"
        color={props.color ?? "default"}
        classNames={{ base: "shrink-0" }}
      />
      {props.showName && (
        <span className="text-sm text-zinc-300">{props.name}</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

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
