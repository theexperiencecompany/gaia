"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * MCP connect-callback query params, owned by this hook. The Composio OAuth
 * params (oauth_success/oauth_error/integration) are owned by the global
 * useOAuthSuccessToast hook instead, so they're intentionally not cleared here.
 */
const MCP_CALLBACK_PARAMS = [
  "status",
  "id",
  "name",
  "error",
  "refresh",
] as const;

export interface IntegrationDeepLinkHandlers {
  /** MCP `status=connected` — toast + open the connected integration's sidebar. */
  onConnected: (integrationId: string, name: string | null) => void;
  /** MCP `status=bearer_required` — open the bearer-token modal. */
  onBearerRequired: (integrationId: string, name: string) => void;
  /** MCP `status=failed` — show an error toast. */
  onFailed: (error: string | null) => void;
  /**
   * Standalone `id` (slash-command nav, marketplace add, custom create) or a
   * Composio OAuth success — open the integration's sidebar. `refresh` means
   * the integration may not be in the cached list yet.
   */
  onOpen: (integrationId: string, opts: { refresh: boolean }) => void;
  /** `?connect=<id>`: start that integration's connect flow on arrival. Used by
   *  the links GAIA puts in chat, so "Connect Gmail" is one tap, not a page
   *  and a search. */
  onConnectRequested: (integrationId: string) => void;
  /** `?connect_error=<reason>`: a bot connect link could not be redeemed. */
  onConnectLinkFailed: (reason: string) => void;
}

function dispatchMcpCallback(
  h: IntegrationDeepLinkHandlers,
  status: string,
  id: string,
  name: string | null,
  error: string | null,
): void {
  if (status === "connected") {
    h.onConnected(id, name);
  } else if (status === "bearer_required" && name) {
    h.onBearerRequired(id, name);
  } else if (status === "failed") {
    h.onFailed(error);
  }
}

/** Drop consumed params from the address bar without a navigation. */
function stripSearchParams(
  router: Pick<ReturnType<typeof useRouter>, "replace">,
  params: readonly string[],
): void {
  const url = new URL(window.location.href);
  const present = params.filter((param) => url.searchParams.has(param));
  if (present.length === 0) return;
  for (const param of present) url.searchParams.delete(param);
  router.replace(url.pathname + url.search, { scroll: false });
}

/**
 * Single, reactive source of truth for backend connect-callback query params on
 * the integrations page. Replaces the previously fragmented mount-only
 * window.location effects, so it fires on soft (client) navigations too — e.g.
 * creating a custom integration while already on /integrations.
 */
export function useIntegrationDeepLink(
  handlers: IntegrationDeepLinkHandlers,
): void {
  const searchParams = useSearchParams();
  const router = useRouter();
  // Read handlers via a ref so the effect doesn't re-run when they're recreated.
  const handlersRef = useRef(handlers);
  // The connect param is consumed once. Stripping it is async (router.replace),
  // so without this the effect can fire the connect twice on the same URL and
  // open two OAuth requests for one tap.
  const consumedConnectRef = useRef<string | null>(null);
  useEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    const status = searchParams.get("status");
    const id = searchParams.get("id");
    const name = searchParams.get("name");
    const error = searchParams.get("error");
    const oauthSuccess = searchParams.get("oauth_success");
    const refresh = searchParams.get("refresh") === "true";
    const connect = searchParams.get("connect");
    const connectError = searchParams.get("connect_error");
    const h = handlersRef.current;

    const stripParams = (params: readonly string[]) =>
      stripSearchParams(router, params);

    // MCP connect callback (always carries both id and status).
    if (status && id) {
      dispatchMcpCallback(h, status, id, name, error);
      stripParams(MCP_CALLBACK_PARAMS);
      return;
    }

    // Composio OAuth success — open the just-connected integration's sidebar.
    // The toast and oauth param cleanup are owned by useOAuthSuccessToast.
    if (oauthSuccess === "true") {
      const targetId = id ?? searchParams.get("integration");
      if (targetId) h.onOpen(targetId, { refresh: true });
      return;
    }

    // Standalone id — slash-command nav, marketplace add, or custom create.
    if (id) {
      h.onOpen(id, { refresh });
      stripParams(MCP_CALLBACK_PARAMS);
      return;
    }

    if (connectError) {
      stripParams(["connect_error"]);
      h.onConnectLinkFailed(connectError);
      return;
    }

    // A connect request from a chat link. Consumed once: the param is stripped
    // before the OAuth redirect so coming back never re-triggers it.
    if (connect && consumedConnectRef.current !== connect) {
      consumedConnectRef.current = connect;
      stripParams(["connect"]);
      h.onConnectRequested(connect);
    }
  }, [searchParams, router]);
}
