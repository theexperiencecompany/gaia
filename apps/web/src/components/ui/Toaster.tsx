"use client";

import { type SileoPosition, Toaster as SileoToaster } from "sileo";

export interface ToasterProps {
  position?: SileoPosition;
}

/**
 * App-wide Toaster configured with dark theme defaults.
 */
export function Toaster({ position = "top-right" }: ToasterProps) {
  return (
    <SileoToaster
      position={position}
      options={{
        fill: "#262626",
        // Sileo auto-expands the description panel by default (autopilot).
        // We want the collapsed pill until the user hovers — hover-expansion
        // is built into sileo and unaffected by this flag.
        autopilot: false,
        styles: {
          title: "text-white! truncate max-w-2xl",
          description: "text-white/75!",
          badge: "bg-white/10!",
          button: "bg-white/10! hover:bg-white/15!",
        },
      }}
    />
  );
}
