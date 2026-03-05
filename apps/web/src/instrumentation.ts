export async function register() {
  // if (process.env.NEXT_RUNTIME === "nodejs") {
  //   await import("../sentry.server.config");
  // }
  // if (process.env.NEXT_RUNTIME === "edge") {
  //   await import("../sentry.edge.config");
  // }
}

export const onRequestError: (
  ...args: Parameters<typeof import("@sentry/nextjs").captureRequestError>
) => ReturnType<typeof import("@sentry/nextjs").captureRequestError> = async (
  ...args
) => {
  const { captureRequestError } = await import("@sentry/nextjs");
  return captureRequestError(...args);
};
