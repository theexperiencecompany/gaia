/**
 * Integration types — single source of truth lives in @gaia/shared.
 * This file is a thin re-export surface so feature code can keep importing
 * from `../types` without leaking the shared package layout.
 */

export type {
  CommunityIntegration,
  CommunityIntegrationsResponse,
  CommunitySearchParams,
  CreateCustomIntegrationRequest,
  Integration,
  IntegrationAuthType,
  IntegrationCategory as IntegrationCategoryValue,
  IntegrationCreator as CommunityIntegrationCreator,
  IntegrationManagedBy,
  IntegrationStatusValue,
  IntegrationTool,
  IntegrationToolsResponse,
  MarketplaceIntegration,
  MyIntegrationItem,
  MyIntegrationsResponse,
  PublicIntegrationResponse,
} from "@gaia/shared";
