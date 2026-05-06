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
  IntegrationStatusRecord as IntegrationStatus,
  IntegrationStatusValue,
  IntegrationsConfigEntry,
  IntegrationsConfigResponse,
  IntegrationsStatusResponse,
  IntegrationTool,
  MarketplaceIntegration,
  PublicIntegrationResponse,
  UserIntegration,
  UserIntegrationsResponse,
} from "@gaia/shared";
