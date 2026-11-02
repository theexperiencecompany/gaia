"use client";

/**
 * HeroUI v3 needs no provider: components read theme tokens directly from CSS
 * and get their router integration from React Aria's own defaults. This stays as
 * a pass-through so the layout tree and its import sites are unchanged.
 */
export function HeroUIProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
