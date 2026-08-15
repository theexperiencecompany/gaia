/**
 * Idle timer for a live SSE turn.
 *
 * The backend follows its event log forever, emitting a keepalive whenever the
 * log is quiet, so a background task that dies without publishing leaves the
 * connection open and silent. Nothing else in the client bounds that: without a
 * watchdog the spinner runs until the tab closes. Every inbound frame —
 * keepalives included — kicks the timer; the window elapsing means the stream
 * went silent even by its own liveness signal.
 */
export class StallWatchdog {
  private handle: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly idleMs: number,
    private readonly onStall: () => void,
  ) {}

  arm(): void {
    this.disarm();
    this.handle = setTimeout(() => {
      this.handle = null;
      this.onStall();
    }, this.idleMs);
  }

  /** A frame arrived — restart the window. No-op once disarmed or fired. */
  kick(): void {
    if (this.handle === null) return;
    this.arm();
  }

  disarm(): void {
    if (this.handle === null) return;
    clearTimeout(this.handle);
    this.handle = null;
  }
}
