import type { ConnectLinkPreviewResponse } from "@shared/api/generated";
import { useEffect, useState } from "react";

import { reportToSentry } from "@/lib/observability/reportToSentry";

import { previewConnectLink } from "../api/connectLinkApi";

export type ConnectLinkPreviewState =
  | { kind: "loading" }
  | { kind: "ready"; preview: ConnectLinkPreviewResponse }
  | { kind: "expired" }
  | { kind: "unavailable" };

/**
 * Preview a connect link's code. A failed preview is reported and leaves the
 * page on its generic copy: the code itself is still good, so Continue stays.
 */
export function useConnectLinkPreview(code: string): ConnectLinkPreviewState {
  const [state, setState] = useState<ConnectLinkPreviewState>({
    kind: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    previewConnectLink(code).then(
      (preview) => {
        if (cancelled) return;
        setState(preview ? { kind: "ready", preview } : { kind: "expired" });
      },
      (error: unknown) => {
        reportToSentry(error);
        if (!cancelled) setState({ kind: "unavailable" });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [code]);

  return state;
}
