"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Pins a popup window to the route it loaded with.
 *
 * The popup reuses the full chat pipeline, and many of its components
 * legitimately navigate on the web (follow-up actions seed the
 * composer and push to /c, links route around the app). In a 420px
 * assistant window any client-side navigation away is wrong — it would
 * render the whole GAIA app inside the popup. Root-cause guard: snap
 * straight back whenever the pathname changes.
 */
export default function PopupRouteLock() {
  const pathname = usePathname();
  const router = useRouter();
  const homeRef = useRef<string | null>(null);

  useEffect(() => {
    if (homeRef.current === null) {
      homeRef.current = pathname;
      return;
    }
    if (pathname !== homeRef.current) {
      router.replace(homeRef.current);
    }
  }, [pathname, router]);

  return null;
}
