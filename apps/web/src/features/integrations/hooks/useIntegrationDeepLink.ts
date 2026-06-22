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
  handlersRef.current = handlers;

  useEffect(() => {
    const status = searchParams.get("status");
    const id = searchParams.get("id");
    const name = searchParams.get("name");
    const error = searchParams.get("error");
    const oauthSuccess = searchParams.get("oauth_success");
    const refresh = searchParams.get("refresh") === "true";
    const h = handlersRef.current;

    const clearMcpParams = () => {
      const url = new URL(window.location.href);
      let changed = false;
      for (const param of MCP_CALLBACK_PARAMS) {
        if (url.searchParams.has(param)) {
          url.searchParams.delete(param);
          changed = true;
        }
      }
      if (changed) {
        router.replace(url.pathname + url.search, { scroll: false });
      }
    };

    // MCP connect callback (always carries both id and status).
    if (status && id) {
      if (status === "connected") {
        h.onConnected(id, name);
      } else if (status === "bearer_required" && name) {
        h.onBearerRequired(id, name);
      } else if (status === "failed") {
        h.onFailed(error);
      }
      clearMcpParams();
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
      clearMcpParams();
    }
  }, [searchParams, router]);
}
