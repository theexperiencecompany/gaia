export function normalizeListResponse<T>(response: { data: T[] } | T[]): T[] {
  if (
    typeof response === "object" &&
    response !== null &&
    "data" in response &&
    Array.isArray((response as { data: T[] }).data)
  ) {
    return (response as { data: T[] }).data;
  }
  return response as T[];
}
