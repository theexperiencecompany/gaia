export async function register() {
  // Sentry auto-instrumentation is intentionally disabled — see apps/web/CLAUDE.md before re-enabling.
}

export const onRequestError: (
  ...args: Parameters<typeof import("@sentry/nextjs").captureRequestError>
) => ReturnType<typeof import("@sentry/nextjs").captureRequestError> = async (
  ...args
) => {
  const { captureRequestError } = await import("@sentry/nextjs");
  return captureRequestError(...args);
};
