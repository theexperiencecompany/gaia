/**
 * Enhanced tool types with integration requirements
 */

export interface ToolIntegrationRequirement {
  toolName: string;
  category: string;
  requiredIntegration: string; // Integration ID from backend
  integrationName: string; // Display name for integration
  description?: string;
  isRequired: boolean; // If true, tool is completely disabled without integration
}

export interface EnhancedToolInfo {
  name: string;
  category: string;
  integration?: ToolIntegrationRequirement;
  isLocked: boolean; // Derived from integration status
}
