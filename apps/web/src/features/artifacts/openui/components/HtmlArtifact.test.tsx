// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ArtifactRenderer } from "../ArtifactRenderer";
import { ARTIFACT_HEIGHT_MESSAGE } from "../constants";

const PROGRAM = `root = Artifact("Mortgage", "Try your numbers", [], [html1])
html1 = HtmlArtifact("Calculator", "<form class=\\"calculator\\" data-calc></form>")`;

function frameOf(container: HTMLElement): HTMLIFrameElement {
  const frame = container.querySelector("iframe");
  if (!frame) throw new Error("HtmlArtifact rendered no frame");
  return frame;
}

// A frame sandboxed without allow-same-origin posts with the opaque origin "null".
function post(source: Window | null, data: unknown, origin = "null") {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source, origin }));
  });
}

describe("HtmlArtifact", () => {
  // Regression: a fixed 34rem frame clipped a taller tool in the PDF and scrolled inside the page on phones.
  it("grows its frame to the height its document reports", () => {
    const { container } = render(<ArtifactRenderer program={PROGRAM} />);
    const frame = frameOf(container);

    post(frame.contentWindow, { type: ARTIFACT_HEIGHT_MESSAGE, height: 1240 });

    expect(frame.style.height).toBe("1240px");
  });

  it("ignores a height from any window or origin but its own sandboxed frame's", () => {
    const { container } = render(<ArtifactRenderer program={PROGRAM} />);
    const frame = frameOf(container);

    post(window, { type: ARTIFACT_HEIGHT_MESSAGE, height: 1240 });
    post(
      frame.contentWindow,
      { type: ARTIFACT_HEIGHT_MESSAGE, height: 1240 },
      "https://evil.example",
    );
    post(frame.contentWindow, {
      type: ARTIFACT_HEIGHT_MESSAGE,
      height: "tall",
    });

    expect(frame.style.height).toBe("");
  });

  it("loads only GAIA's stylesheet and runtime, under the page's theme", () => {
    const { container } = render(<ArtifactRenderer program={PROGRAM} />);
    const doc = new DOMParser().parseFromString(
      frameOf(container).getAttribute("srcdoc") ?? "",
      "text/html",
    );

    const csp = doc.head.firstElementChild?.getAttribute("content") ?? "";
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain(
      `script-src ${window.location.origin}/artifact/gaia-runtime.js`,
    );
    expect(doc.documentElement.dataset.theme).toBe("dark");
    expect(doc.querySelector("main form[data-calc]")).not.toBeNull();
  });
});
