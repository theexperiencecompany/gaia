import stringSimilarity from "string-similarity";

/**
 * Configuration for similarity matching
 */
export interface SimilarityConfig {
  /** Minimum similarity threshold (0-1) */
  threshold: number;
  /** Maximum number of results to return */
  maxResults: number;
}

export const DEFAULT_SIMILARITY_CONFIG: SimilarityConfig = {
  threshold: 0.2,
  maxResults: 7,
};

/**
 * Weighted random selection from an array based on weights
 */
function weightedRandomSelect<T>(items: T[], weights: number[]): T {
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
  let random = Math.random() * totalWeight;

  for (let i = 0; i < items.length; i++) {
    random -= weights[i];
    if (random <= 0) {
      return items[i];
    }
  }

  // Fallback to last item if something goes wrong
  return items[items.length - 1];
}

/**
 * Get a single contextually relevant loading message using weighted random selection
 * Uses string-similarity library with Dice's Coefficient algorithm
 */
export function getRelevantLoadingMessage(
  userMessage: string,
  loadingMessages: string[],
  config: SimilarityConfig,
): string {
  if (!userMessage?.trim()) {
    // Return random message if no user message
    return loadingMessages[Math.floor(Math.random() * loadingMessages.length)];
  }

  // Use string-similarity's findBestMatch to get all similarity ratings
  const results = stringSimilarity.findBestMatch(userMessage, loadingMessages);

  // Filter by threshold
  const relevantResults = results.ratings.filter(
    (item) => item.rating >= config.threshold,
  );

  // If no relevant results, fall back to random selection
  if (relevantResults.length === 0) {
    return loadingMessages[Math.floor(Math.random() * loadingMessages.length)];
  }

  // Create weights - higher ratings get exponentially higher weights
  const messages = relevantResults.map((item) => item.target);
  const weights = relevantResults.map((item) => {
    // Exponential weighting: rating^3 to emphasize higher similarities
    return item.rating ** 3;
  });

  // Use weighted random selection
  return weightedRandomSelect(messages, weights);
}
