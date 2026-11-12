"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { issueLinkContentUrl } from "../api/linkViewerApi";
import { CONTENT_URL_REFRESH_MARGIN_MS } from "../constants";

interface LinkContentUrl {
  /** The signed URL to load the content from; null until the first one arrives. */
  url: string | null;
  /** The content origin refused to load it even with a fresh URL. */
  failed: boolean;
  onLoad: () => void;
  onError: () => void;
}

/**
 * A content URL for a link's framed file, kept fresh: a new one is signed
 * before each expires (10 minutes) and when the element fails to load. An
 * element that already loaded keeps its URL, so an interactive frame is
 * never reloaded under its reader; the fresh URL is used on its next load.
 */
export function useLinkContentUrl(slug: string): LinkContentUrl {
  const [url, setUrl] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const loaded = useRef(false);
  const retried = useRef(false);

  const sign = useCallback(
    async (replaceLoaded: boolean) => {
      const token = await issueLinkContentUrl(slug);
      setExpiresAt(new Date(token.expires_at).getTime());
      if (replaceLoaded || !loaded.current) {
        loaded.current = false;
        setUrl(token.content_url);
      }
    },
    [slug],
  );

  useEffect(() => {
    sign(true).catch((error: unknown) => {
      console.error("Couldn't sign a link content URL:", error);
      setFailed(true);
    });
  }, [sign]);

  useEffect(() => {
    if (expiresAt === null) return;
    const timer = setTimeout(
      () => {
        sign(false).catch((error: unknown) => {
          console.error("Couldn't refresh a link content URL:", error);
        });
      },
      Math.max(0, expiresAt - Date.now() - CONTENT_URL_REFRESH_MARGIN_MS),
    );
    return () => clearTimeout(timer);
  }, [expiresAt, sign]);

  const onLoad = useCallback(() => {
    loaded.current = true;
    retried.current = false;
  }, []);

  const onError = useCallback(() => {
    if (retried.current) {
      setFailed(true);
      return;
    }
    retried.current = true;
    sign(true).catch((error: unknown) => {
      console.error("Couldn't re-sign a link content URL:", error);
      setFailed(true);
    });
  }, [sign]);

  return { url, failed, onLoad, onError };
}
