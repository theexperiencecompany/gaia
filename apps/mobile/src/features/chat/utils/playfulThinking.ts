import {
  DEFAULT_SIMILARITY_CONFIG,
  getRelevantLoadingMessage,
  type SimilarityConfig,
} from "./similarity";

const PLAYFUL_THINKING_MESSAGES = [
  "Asking my mom",
  "Questioning my existence",
  "Phoning a friend",
  "Googling my brain",
  "Talking to myself",
  "Rethinking life choices",
  "Debating with my inner child",
  "Checking the group chat",
  "Reading the manual",
  "Pretending I know",
  "Asking future me",
  "Looking under the bed",
  "Arguing with myself",
  "Guessing confidently",
  "Overthinking as usual",
  "Calling tech support",
  "Drafting a wild guess",
  "Rebooting my brain",
  "Borrowing someone else's notes",
  "Asking the universe",
  "Checking under the couch cushions",
  "Texting my smarter cousin",
  "Forgetting what I was doing",
  "Checking the fridge",
  "Flipping a coin",
  "Rolling dice for answers",
  "Asking Reddit",
  "Reading random fortune cookies",
  "Guessing and hoping",
  "Looking busy",
  "Thinking way too hard",
  "Consulting the magic 8-ball",
  "Second-guessing everything",
  "Wondering why you asked",
  "Asking my therapist",
  "Pretending I studied this",
  "Forgetting what you asked",
  "Refreshing Stack Overflow",
  "Making it up as I go",
  "Copy-pasting from nowhere",
  "Trying to look smart",
  "Pretending I'm Jarvis",
  "Thinking… allegedly",
  "Drafting a wild excuse",
  "Fact-checking my imagination",
  "Wondering if this is legal",
  "Calling customer support (they're busy)",
  "Staring blankly at the wall",
  "Forgetting the question mid-think",
  "Asking my goldfish again",
  "Testing random buttons",
  "Talking to my inner child",
  "Asking the WiFi for help",
  "Checking the fridge again",
  "Guessing with confidence",
  // Additional themed messages for better similarity matching
  "Debugging my thoughts",
  "Compiling wisdom",
  "Searching the internet of things",
  "Analyzing the data in my head",
  "Writing creative algorithms",
  "Processing your request creatively",
  "Researching in my mental database",
  "Brainstorming with my neurons",
  "Calculating the meaning of life",
  "Downloading inspiration",
];

/**
 * Get a random thinking message (original behavior)
 */
export function getRandomThinkingMessage(): string {
  const randomIndex = Math.floor(
    Math.random() * PLAYFUL_THINKING_MESSAGES.length,
  );
  return PLAYFUL_THINKING_MESSAGES[randomIndex];
}

/**
 * Get a contextually relevant thinking message based on user input
 * Falls back to random selection if no relevant matches found
 */
export function getRelevantThinkingMessage(
  userMessage: string,
  config?: Partial<SimilarityConfig>,
): string {
  // If no user message provided, fall back to random
  if (!userMessage?.trim()) {
    return getRandomThinkingMessage();
  }

  try {
    const finalConfig = { ...DEFAULT_SIMILARITY_CONFIG, ...config };

    // Get a single relevant message using weighted random selection
    return getRelevantLoadingMessage(
      userMessage,
      PLAYFUL_THINKING_MESSAGES,
      finalConfig,
    );
  } catch (error) {
    // Graceful fallback on any error
    console.warn(
      "Error getting relevant thinking message, falling back to random:",
      error,
    );
    return getRandomThinkingMessage();
  }
}

/**
 * Export the messages array for external use if needed
 */
export { PLAYFUL_THINKING_MESSAGES };
