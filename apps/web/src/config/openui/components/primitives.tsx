import { Avatar, ProgressBar } from "@heroui/react";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import type { z } from "zod";
import { avatarSchema, progressSchema } from "../promptSpecs";

// Views stay file-private: this module's public surface is the `*Def`
// component registrations at the bottom. Exporting components alongside
// those defs breaks Fast Refresh (react-refresh/only-export-components).

function ProgressView(props: z.infer<typeof progressSchema>) {
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
      <ProgressBar
        value={pct}
        color={props.color === "primary" ? "accent" : (props.color ?? "accent")}
        size="md"
        className="w-full"
      >
        <ProgressBar.Track className="bg-zinc-800">
          <ProgressBar.Fill />
        </ProgressBar.Track>
      </ProgressBar>
    </div>
  );
}

function initialsFrom(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function AvatarView(props: z.infer<typeof avatarSchema>) {
  return (
    <div className="flex items-center gap-2">
      <Avatar
        size="sm"
        color={
          props.color === "primary" ? "accent" : (props.color ?? "default")
        }
        className="shrink-0"
      >
        {props.image && <Avatar.Image src={props.image} alt={props.name} />}
        <Avatar.Fallback>
          {props.initials ?? initialsFrom(props.name)}
        </Avatar.Fallback>
      </Avatar>
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
