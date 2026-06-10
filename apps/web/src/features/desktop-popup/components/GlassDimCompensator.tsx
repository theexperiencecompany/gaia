"use client";

import { useEffect, useState } from "react";

/**
 * Counteracts macOS dimming liquid glass on non-key windows.
 *
 * Nothing in-process controls the material's subdued appearance
 * (NSGlassEffectView properties don't drive it, NSPanels still dim, and
 * swizzling key status destroys the SwiftUI-hosted view — see upstream
 * Meridius-Labs/electron-liquid-glass#64). So instead of fighting
 * AppKit, this overlays a faint brightening layer exactly while the
 * window is unfocused, visually offsetting the dim.
 */
export default function GlassDimCompensator() {
  const [focused, setFocused] = useState(true);

  useEffect(() => {
    const sync = () => setFocused(document.hasFocus());
    sync();
    window.addEventListener("focus", sync);
    window.addEventListener("blur", sync);
    return () => {
      window.removeEventListener("focus", sync);
      window.removeEventListener("blur", sync);
    };
  }, []);

  return (
    <div
      aria-hidden
      className={`pointer-events-none fixed inset-0 z-50 bg-white transition-opacity duration-200 ${
        focused ? "opacity-0" : "opacity-[0.07]"
      }`}
    />
  );
}
