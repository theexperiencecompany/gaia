/**
 * Format tool name for display
 * Converts snake_case tool names to readable format with Title Case
 */
export const formatToolName = (toolName: string | null | undefined): string => {
  if (!toolName) return "";
  return toolName
    .toLowerCase() // First convert to lowercase
    .replace(/_/g, " ") // Replace underscores with spaces
    .replace(/-/g, " ") // Replace dashes with spaces
    .replace(/\b\w/g, (char) => char.toUpperCase()) // Capitalize first letter of each word
    .replace(/\s+tool$/i, "") // Remove "Tool" suffix (case insensitive)
    .trim(); // Trim whitespace
};

/**
 * Capitalize the first letter of each word, preserving the rest of the casing.
 * Treats underscores and dashes as word separators.
 */
export const toTitleCase = (str: string): string => {
  return str
    .replace(/[-_]/g, " ")
    .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1));
};
