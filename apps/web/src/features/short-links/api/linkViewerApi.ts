import { API_BASE } from "@/lib/api/baseUrl";
import { api } from "@/lib/api/typed";
import type {
  ContentTokenResponse,
  LinkEnvelope,
  ReportReason,
} from "@/types/features/shortLinkTypes";

import { REPORT_COPY } from "../constants";

/**
 * Open a link from the viewer's browser, which carries the session cookie (it
 * is host-only on the API host, so server rendering never sees it). Throws the
 * ApiError whose code is the denial the page shows.
 */
export async function resolveLinkInBrowser(
  slug: string,
): Promise<LinkEnvelope> {
  return api.get("/api/v1/l/{slug}", { path: { slug }, silent: true });
}

/** A short-lived URL that loads the link's file from the content origin. */
export async function issueLinkContentUrl(
  slug: string,
): Promise<ContentTokenResponse> {
  return api.post("/api/v1/l/{slug}/content-token", {
    path: { slug },
    silent: true,
  });
}

/** Report a link that breaks GAIA's terms; toasts the outcome. */
export async function reportLink(
  slug: string,
  reason: ReportReason,
  turnstileToken: string | null,
): Promise<void> {
  await api.post("/api/v1/l/{slug}/report", {
    path: { slug },
    body: { reason, turnstile_token: turnstileToken },
    successMessage: REPORT_COPY.sent,
    errorMessage: REPORT_COPY.failed,
  });
}

/** Tell the API this browser opened a link; it decides whether that counts. Never surfaces an error. */
export async function recordShortLinkOpen(slug: string): Promise<void> {
  await api.post("/api/v1/l/{slug}/opened", {
    path: { slug },
    silent: true,
  });
}

/** Browser URL that saves the file behind a link as an attachment. */
export function linkDownloadUrl(slug: string): string {
  return `${API_BASE}/l/${encodeURIComponent(slug)}/download`;
}

/** Browser URL of the PDF export of an artifact slug. */
export function shortLinkPdfDownloadUrl(slug: string): string {
  return `${API_BASE}/l/${encodeURIComponent(slug)}/pdf`;
}
