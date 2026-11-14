import { defineComponent } from "@openuidev/react-lang";
import { useContext } from "react";
import type { z } from "zod";
import { ArtifactAppearanceContext } from "../renderContext";
import { describeArtifactComponent, htmlArtifactSchema } from "../specs";

// The stylesheet and runtime the markup is written against (apps/web/public/artifact/).
const STYLESHEET_PATH = "/artifact/gaia-artifact.css";
const RUNTIME_PATH = "/artifact/gaia-runtime.js";

/**
 * The sandboxed document: an opaque origin (no allow-same-origin), and a CSP that loads only
 * GAIA's stylesheet and runtime, so the markup can neither script nor reach the network.
 */
function sandboxDocument(html: string, theme: "dark" | "light"): string {
  const origin = window.location.origin;
  const csp = [
    "default-src 'none'",
    `style-src ${origin}${STYLESHEET_PATH}`,
    `script-src ${origin}${RUNTIME_PATH}`,
    "img-src data:",
    "font-src data:",
    "form-action 'none'",
    "base-uri 'none'",
  ].join("; ");
  return `<!doctype html><html lang="en" data-theme="${theme}" data-accent="cyan"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><link rel="stylesheet" href="${origin}${STYLESHEET_PATH}"></head><body><main class="doc" data-kind="interactive">${html}</main><script src="${origin}${RUNTIME_PATH}"></script></body></html>`;
}

function HtmlArtifactView({ title, html }: z.infer<typeof htmlArtifactSchema>) {
  const appearance = useContext(ArtifactAppearanceContext);
  return (
    <iframe
      title={title}
      sandbox="allow-scripts"
      srcDoc={sandboxDocument(html, appearance)}
      className="h-[34rem] w-full rounded-2xl border-0 bg-transparent"
    />
  );
}

export const htmlArtifactDef = defineComponent({
  name: "HtmlArtifact",
  description: describeArtifactComponent("HtmlArtifact"),
  props: htmlArtifactSchema,
  component: ({ props }) => <HtmlArtifactView {...props} />,
});
