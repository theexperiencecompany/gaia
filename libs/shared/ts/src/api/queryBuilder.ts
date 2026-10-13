export type QueryValue =
  | string
  | number
  | boolean
  | ReadonlyArray<string | number | boolean>
  | undefined
  | null;

export function buildQueryString(filters?: Record<string, QueryValue>): string {
  if (!filters) return "";
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(filters)) {
    if (value == null || value === "") continue;

    // FastAPI reads a list query param as repeated keys (`labels=a&labels=b`);
    // a single comma-joined value would arrive as one literal `["a,b"]` item.
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item == null || item === "") continue;
        params.append(key, String(item));
      }
      continue;
    }

    if (key === "skip") {
      const limit = filters.limit;
      if (limit != null && limit !== "") {
        const page = Math.floor(Number(value) / Number(limit)) + 1;
        params.append("page", String(page));
      }
    } else if (key === "limit") {
      params.append("per_page", String(value));
    } else {
      params.append(key, String(value));
    }
  }

  const qs = params.toString();
  return qs ? `?${qs}` : "";
}
