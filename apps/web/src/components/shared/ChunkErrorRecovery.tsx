"use client";

import { useEffect } from "react";
import { registerGlobalChunkErrorRecovery } from "@/lib/chunkErrorRecovery";

/**
 * Mounts the global `ChunkLoadError` recovery listeners for the whole app.
 * Renders nothing — it exists only to own the window event subscription for the
 * lifetime of the document. See `@/lib/chunkErrorRecovery` for the mechanism.
 */
export function ChunkErrorRecovery() {
  useEffect(() => registerGlobalChunkErrorRecovery(), []);
  return null;
}
