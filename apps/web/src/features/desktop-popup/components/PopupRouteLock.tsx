"use client";

import { redirect, usePathname } from "next/navigation";
import { useState } from "react";

/**
 * Pins a popup window to the route it loaded with. The popup reuses the full
 * chat pipeline, which legitimately navigates on the web, but in a 420px
 * assistant window any navigation away would render the whole app inside it —
 * so redirect straight back during render (render-time `redirect()` avoids an effect flash).
 */
export default function PopupRouteLock() {
  const pathname = usePathname();
  // Home is pinned via the state initializer, which React evaluates only on
  // the first render — every later render reuses the captured value without
  // any render-phase mutation.
  const [home] = useState(pathname);

  if (pathname !== home) {
    redirect(home);
  }

  return null;
}
