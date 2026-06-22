/**
 * Integration system types and interfaces.
 *
 * The personalized-catalog and per-integration-tools shapes are backend-driven
 * and shared with mobile — they live in `@shared/types` (the canonical source
 * mirroring the API models). Re-exported here so feature code keeps importing
 * from `../types`.
 */

export type {
  IntegrationStatusRecord as IntegrationStatus,
  IntegrationToolsResponse,
  MyIntegrationItem,
  MyIntegrationsResponse,
} from "@shared/types";

/**
 * Integration category values - synced with backend INTEGRATION_CATEGORIES
 * (apps/api/app/services/integrations/category_inference_service.py)
 */
export type IntegrationCategoryValue =
  | "productivity"
  | "communication"
  | "developer"
  | "analytics"
  | "finance"
  | "ai-ml"
  | "education"
  | "personal"
  | "capabilities"
  | "other";

export interface IntegrationInstructions {
  integrationId: string;
  content: string;
  updatedBy: "user" | "agent";
  updatedAt: string | null;
}

export interface Integration {
  id: string;
  name: string;
  description: string;
  category: IntegrationCategoryValue;
  status: "connected" | "not_connected" | "created" | "error";
  displayPriority?: number;
  isFeatured?: boolean;
  managedBy?: "self" | "composio" | "mcp" | "internal";
  available?: boolean;
  authType?: "oauth" | "bearer" | "none";
  source?: "platform" | "custom";
  requiresAuth?: boolean;
  isPublic?: boolean;
  createdBy?: string;
  tools?: Array<{ name: string; description?: string }>;
  toolCount?: number;
  iconUrl?: string;
  creator?: {
    name: string | null;
    picture: string | null;
  } | null;
  slug: string;
}

export interface CreateCustomIntegrationRequest {
  name: string;
  description?: string;
  category?: string;
  server_url: string;
  requires_auth?: boolean;
  auth_type?: "none" | "oauth" | "bearer";
  is_public?: boolean;
  bearer_token?: string;
}

/**
 * Result of connection testing after creating a custom integration
 * Matches backend CustomIntegrationConnectionResult
 */
export interface ConnectionTestResult {
  status: "connected" | "requires_oauth" | "failed" | "created";
  toolsCount?: number;
  oauthUrl?: string;
  error?: string;
}

/**
 * Response from create custom integration endpoint
 * Matches backend CreateCustomIntegrationResponse
 */
export interface CreateCustomIntegrationResponse {
  status: string;
  message: string;
  integrationId: string;
  name: string;
  connection?: ConnectionTestResult;
}

/**
 * Integration connection types for chat messages
 * (Merged from types/features/integrationTypes.ts)
 */
export interface IntegrationConnectionData {
  integration_id: string;
  message: string;
}

/**
 * Suggested public integration from search
 */
export interface SuggestedIntegration {
  id: string;
  name: string;
  description: string;
  category: string;
  iconUrl?: string | null;
  authType?: string | null;
  relevanceScore: number;
  slug: string;
}

/**
 * Data streamed from integration_list_data tool
 */
export interface IntegrationListStreamData {
  hasSuggestions?: boolean;
  suggested?: SuggestedIntegration[];
}

/**
 * Community/Public Marketplace Types
 */

export interface IntegrationHowItWorksStep {
  title: string;
  body: string;
}

export interface IntegrationFAQ {
  question: string;
  answer: string;
}

export interface IntegrationContent {
  useCases: string[];
  howItWorks: IntegrationHowItWorksStep[];
  faqs: IntegrationFAQ[];
}

export interface CommunityIntegrationCreator {
  name: string | null;
  picture: string | null;
}

export interface CommunityIntegration {
  integrationId: string;
  slug: string;
  name: string;
  description: string;
  category: string;
  iconUrl: string | null;
  cloneCount: number;
  toolCount: number;
  tools: Array<{ name: string; description: string | null }>;
  publishedAt: string | null;
  creator: CommunityIntegrationCreator | null;
  source?: "platform" | "custom";
}

export interface CommunityIntegrationsResponse {
  integrations: CommunityIntegration[];
  total: number;
  hasMore: boolean;
}

export interface PublicIntegrationResponse extends CommunityIntegration {
  mcpConfig?: {
    serverUrl: string;
    requiresAuth: boolean;
    authType: string | null;
  } | null;
  source?: "platform" | "custom";
  authType?: "oauth" | "bearer" | "none" | null;
  content?: IntegrationContent | null;
}
