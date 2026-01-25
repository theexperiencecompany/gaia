/**
 * Fetch all pages from a paginated API endpoint
 */
export async function fetchAllPaginated<T>(
  fetchPage: (
    limit: number,
    offset: number,
  ) => Promise<{ items: T[]; total: number; hasMore: boolean }>,
  batchSize = 100,
): Promise<T[]> {
  const allItems: T[] = [];
  let offset = 0;
  let hasMore = true;

  while (hasMore) {
    try {
      const result = await fetchPage(batchSize, offset);
      allItems.push(...result.items);

      offset += batchSize;
      hasMore = result.hasMore && result.items.length === batchSize;
    } catch (error) {
      console.error(`[fetchAllPaginated] Error at offset ${offset}:`, error);
      break;
    }
  }

  return allItems;
}

/**
 * Check if running in development mode
 */
export function isDevelopment(): boolean {
  return process.env.NODE_ENV === "development";
}
