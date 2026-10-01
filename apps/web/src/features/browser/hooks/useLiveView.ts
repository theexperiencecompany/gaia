import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import {
  browserApi,
  liveViewPageUrl,
  liveViewSocketUrl,
} from "../api/browserApi";

// The API ends a live-view socket when its token lapses, so a fresh token is
// minted this long before that, while the old socket is still up.
const TOKEN_RENEW_LEAD_SECONDS = 60;

/**
 * The tokened socket and page URLs for a session's live view.
 *
 * The live view's vhost never sees the session cookie, so every connection
 * carries a takeover token. One token per session is shared by every surface
 * showing it (card, handoff prompt, side panel), re-minted before it expires,
 * and re-minted on demand by `renew` when a socket drops, so a reconnect never
 * redials with a dead token.
 */
export function useLiveView(
  sessionId: string | null | undefined,
  liveViewUrl: string | null | undefined,
) {
  const enabled = !!sessionId && !!liveViewUrl;
  const { data, refetch } = useQuery({
    queryKey: ["browser-live-view-token", sessionId],
    queryFn: () => browserApi.getLiveViewToken(sessionId as string),
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    // A remount gets a fresh token rather than one cached close to its expiry.
    gcTime: 0,
    // A refusal means the session is gone; asking again cannot change that.
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: ({ state }) =>
      state.status === "success" && state.data
        ? Math.max(state.data.expires_in - TOKEN_RENEW_LEAD_SECONDS, 0) * 1000
        : false,
    refetchIntervalInBackground: true,
  });
  const renew = useCallback(() => {
    void refetch();
  }, [refetch]);

  const token = enabled ? data?.token : undefined;
  return {
    socketUrl:
      token && liveViewUrl ? liveViewSocketUrl(liveViewUrl, token) : null,
    pageUrl: token && liveViewUrl ? liveViewPageUrl(liveViewUrl, token) : null,
    renew,
  };
}
