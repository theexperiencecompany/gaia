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
        styles: {
          title: "text-white!",
          description: "text-white/75!",
          badge: "bg-white/10!",
          button: "bg-white/10! hover:bg-white/15!",
        },
      }}
    />
  );
}
