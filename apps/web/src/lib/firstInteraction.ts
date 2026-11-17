const INTERACTION_EVENTS = [
  "pointerdown",
  "keydown",
  "touchstart",
  "scroll",
] as const;

/** Run callback once, on the visitor's first pointer, key, touch or scroll; returns a cancel function. */
export function onFirstInteraction(callback: () => void): () => void {
  const stop = () => {
    for (const event of INTERACTION_EVENTS) {
      window.removeEventListener(event, handle);
    }
  };
  function handle() {
    stop();
    callback();
  }
  for (const event of INTERACTION_EVENTS) {
    window.addEventListener(event, handle, { passive: true });
  }
  return stop;
}
