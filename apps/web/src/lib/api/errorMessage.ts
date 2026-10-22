/** The API's own words for a failed call (the error envelope's message), when it gave any. */
export function apiErrorMessage(err: unknown): string | undefined {
  return err instanceof Error && err.message ? err.message : undefined;
}
