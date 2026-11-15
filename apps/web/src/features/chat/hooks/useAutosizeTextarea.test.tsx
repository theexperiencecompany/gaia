// @vitest-environment jsdom

import { render } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";

import { useAutosizeTextarea } from "@/features/chat/hooks/useAutosizeTextarea";

const LINE_PX = 24;

function Field({ value }: { value: string }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useAutosizeTextarea(ref, value);
  return <textarea ref={ref} value={value} readOnly />;
}

/** jsdom has no layout, so scrollHeight follows the line count like a browser would. */
function stubScrollHeight(textarea: HTMLTextAreaElement): void {
  Object.defineProperty(textarea, "scrollHeight", {
    configurable: true,
    get: () => textarea.value.split("\n").length * LINE_PX,
  });
}

describe("useAutosizeTextarea", () => {
  it("sizes the textarea to its content and follows it as lines are added and removed", () => {
    const { container, rerender } = render(<Field value="one" />);
    const textarea = container.querySelector("textarea");
    if (!textarea) throw new Error("textarea not rendered");
    stubScrollHeight(textarea);

    rerender(<Field value={"one\ntwo\nthree"} />);
    expect(textarea.style.height).toBe(`${3 * LINE_PX}px`);

    rerender(<Field value="one" />);
    expect(textarea.style.height).toBe(`${LINE_PX}px`);
  });
});
