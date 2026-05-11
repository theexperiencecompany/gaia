/**
 * Format tool name for display
 * Converts snake_case tool names to readable format with Title Case
 */
export const formatToolName = (toolName: string): string => {
  return toolName
    .toLowerCase() // First convert to lowercase
    .replace(/_/g, " ") // Replace underscores with spaces
    .replace(/-/g, " ") // Replace dashes with spaces
    .replace(/\b\w/g, (char) => char.toUpperCase()) // Capitalize first letter of each word
    .replace(/\s+tool$/i, "") // Remove "Tool" suffix (case insensitive)
    .trim(); // Trim whitespace
};
