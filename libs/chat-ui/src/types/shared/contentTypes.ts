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
export interface ToolInfo {
  name: string;
  description: string;
  category: string;
}

/**
 * Step information for instructions/guides
 */
export interface StepInfo {
  title: string;
  description: string;
  details?: string;
}
