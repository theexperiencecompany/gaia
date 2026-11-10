/**
 * Bounds a promise that has no timeout of its own: settles with it, or rejects
 * with `Error(reason)` after `ms`. The timer is always cleared, so a promise that
 * wins never leaves one pending.
 */
export async function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  reason: string,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(reason)), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}
