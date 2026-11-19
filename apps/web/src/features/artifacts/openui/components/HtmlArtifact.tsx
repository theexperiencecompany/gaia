import {
  describeArtifactComponent,
  htmlArtifactSchema,
} from "@gaia/artifacts/specs";
import { defineComponent } from "@openuidev/react-lang";
import { type RefObject, useContext, useEffect, useRef, useState } from "react";
import type { z } from "zod";
import {
  AgentHtmlFrame,
  ARTIFACT_RUNTIME_PATH,
  ARTIFACT_STYLESHEET_PATH,
} from "@/components/shared/AgentHtmlFrame";
import { ARTIFACT_HEIGHT_MESSAGE } from "../constants";
import { ArtifactAppearanceContext } from "../renderContext";

// What a frame sandboxed without allow-same-origin posts as its origin.
const OPAQUE_ORIGIN = "null";

/** The markup under GAIA's artifact stylesheet and runtime, in the page's appearance. */
function markupDocument(html: string, theme: "dark" | "light"): string {
  const origin = window.location.origin;
  return `<html lang="en" data-theme="${theme}" data-accent="cyan"><head><link rel="stylesheet" href="${origin}${ARTIFACT_STYLESHEET_PATH}"></head><body><main class="doc" data-kind="interactive">${html}</main><script src="${origin}${ARTIFACT_RUNTIME_PATH}"></script></body></html>`;
}

interface HeightMessage {
  type?: unknown;
  height?: unknown;
}

/** The height the frame's own runtime last reported for its document; null until it has. */
function useReportedHeight(
  frame: RefObject<HTMLIFrameElement | null>,
): number | null {
  const [height, setHeight] = useState<number | null>(null);
  useEffect(() => {
    const onMessage = (event: MessageEvent<HeightMessage | null>) => {
      const own = frame.current?.contentWindow;
      if (!own || event.source !== own || event.origin !== OPAQUE_ORIGIN)
        return;
      const reported = event.data?.height;
      if (
        event.data?.type === ARTIFACT_HEIGHT_MESSAGE &&
        typeof reported === "number" &&
        Number.isFinite(reported)
      )
        setHeight(reported);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [frame]);
  return height;
}

/** The frame fits its document, so the page (and a printed PDF) shows it whole with no inner scroll. */
function HtmlArtifactView({ title, html }: z.infer<typeof htmlArtifactSchema>) {
  const appearance = useContext(ArtifactAppearanceContext);
  const frame = useRef<HTMLIFrameElement>(null);
  const height = useReportedHeight(frame);
  return (
    <AgentHtmlFrame
      trust="markup"
      ref={frame}
      title={title}
      html={markupDocument(html, appearance)}
      // 34rem holds the frame until its runtime has measured the document
      className="h-[34rem] w-full rounded-2xl border-0 bg-transparent"
      style={height === null ? undefined : { height }}
    />
  );
}

export const htmlArtifactDef = defineComponent({
  name: "HtmlArtifact",
  description: describeArtifactComponent("HtmlArtifact"),
  props: htmlArtifactSchema,
  component: ({ props }) => <HtmlArtifactView {...props} />,
});
