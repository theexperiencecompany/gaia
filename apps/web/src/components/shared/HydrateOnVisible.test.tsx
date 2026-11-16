// @vitest-environment jsdom
import { act, startTransition, useState } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HydrateOnVisible } from "./HydrateOnVisible";

type ObserverCallback = (entries: { isIntersecting: boolean }[]) => void;

const observers = new Set<ObserverCallback>();

class StubIntersectionObserver {
  private readonly callback: ObserverCallback;
  constructor(callback: ObserverCallback) {
    this.callback = callback;
  }
  observe() {
    observers.add(this.callback);
  }
  disconnect() {
    observers.delete(this.callback);
  }
}

async function scrollIntoRange() {
  await act(async () => {
    for (const callback of [...observers]) callback([{ isIntersecting: true }]);
  });
}

function Section({ heading }: { heading: string }) {
  const [clicks, setClicks] = useState(0);
  return (
    <section data-testid="section">
      <h2>{heading}</h2>
      <a href="#pricing">Pricing</a>
      <button type="button" onClick={() => setClicks(clicks + 1)}>
        Clicked {clicks}
      </button>
    </section>
  );
}

function Page({ heading = "Plans" }: { heading?: string }) {
  return (
    <main>
      <h1>{heading}</h1>
      <HydrateOnVisible>
        <Section heading={heading} />
      </HydrateOnVisible>
    </main>
  );
}

/** Render like the server does: no window global, so the component cannot see a browser. */
function renderOnServer(): string {
  const browserWindow = globalThis.window;
  vi.stubGlobal("window", undefined);
  try {
    return renderToString(<Page />);
  } finally {
    vi.stubGlobal("window", browserWindow);
  }
}

const container = () => document.getElementById("root") as HTMLElement;
const sections = () => container().querySelectorAll("[data-testid=section]");

let root: Root | null = null;

beforeEach(() => {
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("IntersectionObserver", StubIntersectionObserver);
  document.body.innerHTML = '<div id="root"></div>';
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  observers.clear();
  vi.unstubAllGlobals();
});

async function hydrateServerHtml() {
  container().innerHTML = renderOnServer();
  const section = sections()[0];
  await act(async () => {
    root = hydrateRoot(container(), <Page />);
  });
  return section;
}

describe("HydrateOnVisible", () => {
  it("server-renders its children", () => {
    container().innerHTML = renderOnServer();

    expect(sections()).toHaveLength(1);
    expect(container().textContent).toContain("Clicked 0");
  });

  it("keeps the server DOM untouched until the section nears the viewport", async () => {
    const section = await hydrateServerHtml();

    expect(sections()).toHaveLength(1);
    expect(sections()[0]).toBe(section);
    expect(observers.size).toBe(1);
  });

  it("hydrates the same server nodes in place once the section nears the viewport", async () => {
    const section = await hydrateServerHtml();

    await scrollIntoRange();

    expect(sections()).toHaveLength(1);
    expect(sections()[0]).toBe(section);
    expect(section.isConnected).toBe(true);
    const button = section.querySelector("button") as HTMLButtonElement;
    await act(async () => button.click());
    expect(button.textContent).toBe("Clicked 1");
  });

  it("keeps focus on a server link across hydration", async () => {
    const section = await hydrateServerHtml();
    const link = section.querySelector("a") as HTMLAnchorElement;
    link.focus();
    expect(document.activeElement).toBe(link);

    await scrollIntoRange();

    expect(link.isConnected).toBe(true);
    expect(document.activeElement).toBe(link);
  });

  it("keeps the server nodes through a parent re-render, then hydrates them with the latest props", async () => {
    const section = await hydrateServerHtml();

    await act(async () => root?.render(<Page heading="Pricing plans" />));

    expect(container().querySelector("h1")?.textContent).toBe("Pricing plans");
    expect(sections()[0]).toBe(section);
    expect(section.querySelector("h2")?.textContent).toBe("Plans");

    await scrollIntoRange();

    expect(sections()).toHaveLength(1);
    expect(sections()[0]).toBe(section);
    expect(section.querySelector("h2")?.textContent).toBe("Pricing plans");
  });

  it("lets a transition re-render the page commit without waiting for the section", async () => {
    const section = await hydrateServerHtml();

    await act(async () => {
      startTransition(() => root?.render(<Page heading="Pricing plans" />));
    });

    expect(container().querySelector("h1")?.textContent).toBe("Pricing plans");
    expect(sections()[0]).toBe(section);
  });

  it("hydrates at once and handles a click that lands before the section nears the viewport", async () => {
    const section = await hydrateServerHtml();
    const button = section.querySelector("button") as HTMLButtonElement;

    await act(async () => {
      button.dispatchEvent(new Event("pointerdown", { bubbles: true }));
      button.click();
    });

    expect(sections()[0]).toBe(section);
    expect(button.textContent).toBe("Clicked 1");
  });

  it("renders its children at once in a client render", async () => {
    await act(async () => {
      root = createRoot(container());
      root.render(<Page />);
    });

    expect(sections()).toHaveLength(1);
    expect(observers.size).toBe(0);
  });
});
