// @vitest-environment jsdom
/** A tool card's "View more" follows its description's current clamp, not only the first measurement. */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToolList } from "@/app/[locale]/(landing)/marketplace/[slug]/ToolList";

type ObserverCallback = (entries: Partial<IntersectionObserverEntry>[]) => void;

let intersect: ObserverCallback = () => undefined;
let resize: ObserverCallback = () => undefined;
const resized = new Set<Element>();

/** Hands the list only the entries a test passes to intersect(). */
class FakeIntersectionObserver {
  constructor(callback: ObserverCallback) {
    intersect = callback;
  }
  observe() {
    // entries come from intersect(), not from observing
  }
  unobserve() {
    // entries come from intersect(), not from observing
  }
  disconnect() {
    // entries come from intersect(), not from observing
  }
}

class FakeResizeObserver {
  constructor(callback: ObserverCallback) {
    resize = callback;
  }
  observe(target: Element) {
    resized.add(target);
  }
  unobserve(target: Element) {
    resized.delete(target);
  }
  disconnect() {
    resized.clear();
  }
}

/** Give the element a fixed client height and a content height the test can change. */
function sizeElement(element: HTMLElement, clientHeight: number) {
  let scrollHeight = clientHeight;
  Object.defineProperty(element, "clientHeight", { value: clientHeight });
  Object.defineProperty(element, "scrollHeight", { get: () => scrollHeight });
  return (next: number) => {
    scrollHeight = next;
  };
}

function resizeAll() {
  act(() => resize([...resized].map((target) => ({ target }))));
}

describe("marketplace ToolList clamp toggle", () => {
  beforeEach(() => {
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resized.clear();
  });

  it("offers View more when a description that fit is clamped after the viewport narrows, and keeps View less while expanded", () => {
    render(
      <ToolList
        items={[{ key: "TOOL", label: "A tool", description: "Some text" }]}
      />,
    );
    const description = screen.getByText("Some text");
    const setContentHeight = sizeElement(description, 40);

    act(() => intersect([{ target: description, isIntersecting: true }]));
    resizeAll();
    expect(screen.queryByText("View more")).toBeNull();

    setContentHeight(80);
    resizeAll();
    fireEvent.click(screen.getByText("View more"));

    setContentHeight(40);
    resizeAll();
    fireEvent.click(screen.getByText("View less"));

    setContentHeight(80);
    resizeAll();
    expect(screen.getByText("View more")).toBeTruthy();
  });
});
