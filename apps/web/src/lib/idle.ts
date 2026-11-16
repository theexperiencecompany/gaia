/** Run callback once the browser is idle; Safari has no requestIdleCallback, so there it runs after fallbackDelayMs. */
export function whenIdle(
  callback: () => unknown,
  {
    timeoutMs,
    fallbackDelayMs,
  }: { timeoutMs: number; fallbackDelayMs: number },
): void {
  if ("requestIdleCallback" in window) {
    requestIdleCallback(callback, { timeout: timeoutMs });
  } else {
    setTimeout(callback, fallbackDelayMs);
  }
}
