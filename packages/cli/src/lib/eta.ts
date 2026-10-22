/**
 * Time left on a transfer, from its recent rate: a moving window rather than
 * the whole run's average, so a slow start does not haunt the estimate.
 * @module lib/eta
 */

/** How far back the rate looks. */
const WINDOW_MS = 10_000;
/** Less than this of movement is too little to call a rate. */
const MIN_SPAN_MS = 2_000;

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;

interface Sample {
  at: number;
  done: number;
}

export interface EtaTracker {
  /** Record progress; returns the milliseconds left, or null while unknown. */
  update(done: number, total: number): number | null;
}

export function createEtaTracker(now: () => number = Date.now): EtaTracker {
  const samples: Sample[] = [];
  return {
    update(done, total) {
      const at = now();
      samples.push({ at, done });
      while (samples.length > 2 && at - (samples[1]?.at ?? at) >= WINDOW_MS) {
        samples.shift();
      }
      const first = samples[0];
      if (!first || at - first.at < MIN_SPAN_MS) return null;
      const rate = (done - first.done) / (at - first.at);
      if (rate <= 0) return null;
      return Math.round(Math.max(0, total - done) / rate);
    },
  };
}

/** "less than a minute left", "about 4 min left", "about 2 h left". */
export function formatEta(ms: number): string {
  if (ms < MINUTE_MS) return "less than a minute left";
  if (ms < HOUR_MS) return `about ${Math.round(ms / MINUTE_MS)} min left`;
  return `about ${Math.round(ms / HOUR_MS)} h left`;
}
