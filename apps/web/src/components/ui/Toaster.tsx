"use client";

import { Toaster as SileoToaster } from "sileo";

/**
 * App-wide Toaster configured with dark theme defaults.
 */
export function Toaster() {
  return (
    <SileoToaster
      position="top-right"
      options={{
        fill: "#171717",
        roundness: 16,
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
