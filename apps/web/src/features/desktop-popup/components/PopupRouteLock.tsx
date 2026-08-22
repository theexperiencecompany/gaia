"use client";

import { redirect, usePathname } from "next/navigation";
import { useState } from "react";

/**
 * Pins a popup window to the route it loaded with.
 *
 * The popup reuses the full chat pipeline, and many of its components
 * legitimately navigate on the web (follow-up actions seed the
 * composer and push to /c, links route around the app). In a 420px
 * assistant window any client-side navigation away is wrong — it would
 * render the whole GAIA app inside the popup. Root-cause guard: redirect
 * straight back during render whenever the pathname changes (render-time
 * `redirect()` is supported in Client Components, so no effect flash).
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
