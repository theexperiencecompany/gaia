/**
 * Idle timer for a live SSE turn: the backend emits a keepalive whenever its
 * event log is quiet, so a background task that dies without publishing
 * leaves the connection open and silent with nothing else bounding it. Every
 * inbound frame, keepalives included, kicks the timer.
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
