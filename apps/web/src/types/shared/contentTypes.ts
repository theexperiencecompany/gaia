/**
 * Shared types between workflows and use-cases
 */

/**
 * Creator/Author information for community content
 */
export interface ContentCreator {
  id: string;
  name: string;
  avatar?: string;
}

/**
 * Tool information with category for icon display
 */
interface ToolInfo {
  name: string;
  description: string;
  category: string;
}

/**
 * Step information for instructions/guides
 */
interface StepInfo {
  title: string;
  description: string;
  details?: string;
}
