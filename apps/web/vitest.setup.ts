// HeroUI's LazyMotion users (ripple, tooltip, modal, toast, …) import this bundle
// on first render; loaded up front, its setState can no longer land after a test
// file's jsdom teardown ("window is not defined").
import "@heroui/dom-animation";

// jsdom has no layout, so it has no ResizeObserver; HeroUI Tabs and cmdk measure
// themselves with one on mount. A test that needs real sizes stubs its own.
if (typeof window !== "undefined" && !("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {
      // no-op: jsdom has no layout to observe
    }
    unobserve() {
      // no-op: jsdom has no layout to observe
    }
    disconnect() {
      // no-op: jsdom has no layout to observe
    }
  };
}
