"use client";

import { useSearchParams } from "next/navigation";
import { type Dispatch, useEffect, useRef } from "react";

import { toast } from "@/lib/toast";

import { FIELD_NAMES } from "../constants";
import type { Action } from "../state/types";

export function useOAuthCallback(dispatch: Dispatch<Action>): void {
  const searchParams = useSearchParams();
  const handledRef = useRef<string | null>(null);

  useEffect(() => {
    const oauthSuccess = searchParams.get("oauth_success");
    const oauthError = searchParams.get("oauth_error");

    if (!oauthSuccess && !oauthError) return;

    const key = `${oauthSuccess ?? ""}:${oauthError ?? ""}`;
    if (handledRef.current === key) return;
    handledRef.current = key;

    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("oauth_success");
      url.searchParams.delete("oauth_error");
      url.searchParams.delete("integration");
      window.history.replaceState({}, "", url.toString());
    }

    if (oauthSuccess === "true") {
      toast.success("Gmail connected!");
      dispatch({
        type: "answer",
        field: FIELD_NAMES.GMAIL,
        value: "connected",
      });
      return;
    }

    if (oauthError) {
      if (oauthError === "cancelled") {
        toast.error("Connection cancelled. You can try again anytime.");
      } else {
        toast.error("Connection failed. Please try again.");
      }
    }
  }, [searchParams, dispatch]);
}
