import type { ComponentPropsWithRef } from "react";

/**
 * How far agent-made HTML is trusted. "page" is a whole document the agent wrote (a report that
 * draws charts from a CDN): it runs, but can send nothing anywhere. "markup" is an HtmlArtifact's
 * structure, validated to hold no script of its own: only GAIA's artifact stylesheet and runtime load.
 */
export type AgentHtmlTrust = "page" | "markup";

/** No same-origin (no storage or cookies) and no top navigation (it cannot redirect the tab). */
const SANDBOX: Record<AgentHtmlTrust, string> = {
  page: "allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads",
  markup: "allow-scripts",
};

// The stylesheet and runtime HtmlArtifact markup is written against (apps/web/public/artifact/).
export const ARTIFACT_STYLESHEET_PATH = "/artifact/gaia-artifact.css";
export const ARTIFACT_RUNTIME_PATH = "/artifact/gaia-runtime.js";

// Mirrors _FRAME_ACTIVE_CSP (apps/api/app/services/links/serving.py) less what a <meta> cannot carry.
const PAGE_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline' 'unsafe-eval' https:",
  "style-src 'unsafe-inline' https:",
  "img-src data: blob: https:",
  "font-src data: https:",
  "media-src data: blob: https:",
  "connect-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
  "frame-src 'none'",
  "worker-src 'none'",
].join("; ");

function markupCsp(origin: string): string {
  return [
    "default-src 'none'",
    `style-src ${origin}${ARTIFACT_STYLESHEET_PATH}`,
    `script-src ${origin}${ARTIFACT_RUNTIME_PATH}`,
    "img-src data:",
    "font-src data:",
    "form-action 'none'",
    "base-uri 'none'",
  ].join("; ");
}

function cspFor(trust: AgentHtmlTrust): string {
  return trust === "page" ? PAGE_CSP : markupCsp(window.location.origin);
}

/** The document a frame shows: the policy first, then every byte the agent wrote. */
function framedDocument(html: string, trust: AgentHtmlTrust): string {
  // The parser folds the agent's own <html>/<head> into these, so nothing it wrote precedes the policy.
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${cspFor(trust)}">${html}`;
}

type FrameProps = Omit<
  ComponentPropsWithRef<"iframe">,
  "src" | "srcDoc" | "sandbox" | "referrerPolicy"
>;

type AgentHtmlFrameProps = FrameProps &
  (
    | {
        trust: "page" /** Served by the content origin, whose CSP header holds the policy. */;
        src: string;
      }
    | { trust: AgentHtmlTrust; html: string }
  );

/** The one frame agent-made HTML renders in, wherever it is shown and whoever opens it. */
export function AgentHtmlFrame(props: AgentHtmlFrameProps) {
  if ("src" in props) {
    const { trust, src, ...frame } = props;
    return (
      <iframe
        {...frame}
        src={src}
        sandbox={SANDBOX[trust]}
        referrerPolicy="no-referrer"
      />
    );
  }
  const { trust, html, ...frame } = props;
  return (
    <iframe
      {...frame}
      srcDoc={framedDocument(html, trust)}
      sandbox={SANDBOX[trust]}
      referrerPolicy="no-referrer"
    />
  );
}
