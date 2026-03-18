export function buildQueryString(
  filters?: Record<string, string | number | boolean | undefined | null>,
): string {
  if (!filters) return "";
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(filters)) {
    if (value == null || value === "") continue;

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
