"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { sanitizeRedirectUrl } from "@/lib/url-safety";
import { integrationsApi } from "../api/integrationsApi";
import { integrationKeys, toolKeys } from "../api/queryKeys";
import { CLI_CONNECT_POLL_INTERVAL_MS } from "../constants/connect";
import type { CliConnectPhase, ConnectIntegrationResponse } from "../types";

/** Phases that still need the backend to make progress on its own. */
const POLLED_PHASES: readonly CliConnectPhase[] = [
  "installing",
  "awaiting_approval",
];

/** First absolute link in a block of prose, stopping at prose/markup delimiters. */
const URL_IN_TEXT = /https?:\/\/[^\s<>"')\]]+/;

/** Sentence punctuation the tool's prose leaves glued to the end of a link. */
const TRAILING_PUNCTUATION = /[.,;:!?]+$/;

export interface CliConnectState {
  /** `null` until the first response lands. */
  phase: CliConnectPhase | null;
  /**
   * The tool's own output for this phase, relayed verbatim — the approval text
   * while waiting, the failure detail once it failed.
   */
  instructions: string | null;
  /** The approval link found in `instructions`, so it can be offered as a button. */
  approvalUrl: string | null;
  tokenLabel: string | null;
  tokenHelpUrl: string | null;
  /** Backend prose, shown while the tool has produced no output of its own. */
  message: string | null;
  /** Set only when the connection failed. */
  error: string | null;
  /** True while a pasted token is in flight. */
  isSubmittingToken: boolean;
}

const INITIAL_STATE: CliConnectState = {
  phase: null,
  instructions: null,
  approvalUrl: null,
  tokenLabel: null,
  tokenHelpUrl: null,
  message: null,
  error: null,
  isSubmittingToken: false,
};

/**
 * Pull the approval link out of the tool's login output.
 *
 * Vendors word (and reword) that output freely, so the link is found by scan
 * rather than by parsing a known format, and sanitized before it is ever
 * offered to the user.
 */
function findApprovalUrl(instructions: string | null): string | null {
  if (!instructions) return null;
  const match = instructions.match(URL_IN_TEXT);
  if (!match) return null;
  return sanitizeRedirectUrl(match[0].replace(TRAILING_PUNCTUATION, ""));
}

export interface UseCliConnectOptions {
  /**
   * The integration to connect, or `null` to stay idle. Passing `null` stops
   * an in-flight run, so callers close the flow by clearing this.
   */
  integrationId: string | null;
  /** Runs once the tool reports a live connection, with the integration name. */
  onConnected: (name: string) => void;
}

export interface UseCliConnectResult {
  state: CliConnectState;
  /** Sends a pasted token and resumes polling. */
  submitToken: (token: string) => void;
  /** Restarts a failed connection from the top. */
  retry: () => void;
}

/**
 * Resolve the phase from a connect response.
 *
 * The top-level status wins over `cli.phase` so a backend that reports failure
 * or success without a matching phase can't strand the UI. A CLI connect never
 * redirects, and a `pending` with no `cli` block leaves nothing to show or poll
 * on, so both fall through to `failed` rather than spinning forever.
 */
function derivePhase(response: ConnectIntegrationResponse): CliConnectPhase {
  if (response.status === "error") return "failed";
  if (response.status === "connected") return "connected";
  if (response.cli) return response.cli.phase;
  return "failed";
}

type PollStep = (
  integrationId: string,
  runId: number,
  bearerToken?: string,
) => Promise<void>;

/**
 * Drives a `managedBy: "cli"` connection.
 *
 * The connect endpoint is idempotent and advances the connection one step per
 * call, so this re-POSTs it on an interval while the phase is a waiting one and
 * stops the moment the flow needs the user (`needs_token`) or is over
 * (`connected`, `failed`). Every run carries a generation number: closing the
 * flow, submitting a token, or retrying bumps it, so a response from an
 * abandoned run is dropped instead of overwriting the live one — and the
 * pending timer is always cleared, including on unmount.
 */
export function useCliConnect({
  integrationId,
  onConnected,
}: UseCliConnectOptions): UseCliConnectResult {
  const queryClient = useQueryClient();
  const [state, setState] = useState<CliConnectState>(INITIAL_STATE);

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runIdRef = useRef(0);

  // Held in a ref so a caller's inline callback doesn't restart the flow on
  // every render.
  const onConnectedRef = useRef(onConnected);
  useEffect(() => {
    onConnectedRef.current = onConnected;
  });

  const clearPendingTick = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const step = useCallback<PollStep>(
    async (id, runId, bearerToken) => {
      let response: ConnectIntegrationResponse;
      try {
        response = await integrationsApi.postConnect(id, {
          bearerToken,
          // Failures are rendered inside the modal; a toast per poll tick
          // would bury the screen.
          silent: true,
        });
      } catch (error) {
        if (runId !== runIdRef.current) return;
        setState((previous) => ({
          ...previous,
          phase: "failed",
          error: error instanceof Error ? error.message : "Connection failed",
          isSubmittingToken: false,
        }));
        return;
      }

      if (runId !== runIdRef.current) return;

      const cli = response.cli ?? null;
      const phase = derivePhase(response);
      const instructions = cli?.instructions ?? null;

      setState({
        phase,
        instructions,
        approvalUrl: findApprovalUrl(instructions),
        tokenLabel: cli?.tokenLabel ?? null,
        tokenHelpUrl: cli?.tokenHelpUrl ?? null,
        message: response.message ?? null,
        error:
          phase === "failed"
            ? (response.error ?? response.message ?? "Connection failed")
            : null,
        isSubmittingToken: false,
      });

      if (phase === "connected") {
        // Invalidate rather than refetch: the list and the tool picker catch up
        // in the background while the flow closes.
        queryClient.invalidateQueries({ queryKey: integrationKeys.all });
        queryClient.invalidateQueries({ queryKey: toolKeys.all });
        onConnectedRef.current(response.name);
        return;
      }

      if (!POLLED_PHASES.includes(phase)) return;

      timeoutRef.current = setTimeout(() => {
        timeoutRef.current = null;
        void step(id, runId);
      }, CLI_CONNECT_POLL_INTERVAL_MS);
    },
    [queryClient],
  );

  /** Abandons the current run, then starts a fresh one. */
  const start = useCallback(
    (id: string, bearerToken?: string) => {
      clearPendingTick();
      runIdRef.current += 1;
      void step(id, runIdRef.current, bearerToken);
    },
    [clearPendingTick, step],
  );

  useEffect(() => {
    if (!integrationId) return;

    setState(INITIAL_STATE);
    start(integrationId);

    return () => {
      clearPendingTick();
      // Bumping the generation makes any in-flight response a no-op.
      runIdRef.current += 1;
    };
  }, [integrationId, start, clearPendingTick]);

  const submitToken = useCallback(
    (token: string) => {
      if (!integrationId) return;
      setState((previous) => ({
        ...previous,
        isSubmittingToken: true,
        error: null,
      }));
      start(integrationId, token);
    },
    [integrationId, start],
  );

  const retry = useCallback(() => {
    if (!integrationId) return;
    setState(INITIAL_STATE);
    start(integrationId);
  }, [integrationId, start]);

  return { state, submitToken, retry };
}
