/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type {
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
  Integration,
  IntegrationStatus,
} from "@/features/integrations/types";

export interface UseIntegrationsReturn {
  integrations: Integration[];
  isLoading: boolean;
  error: Error | null;
  getIntegrationStatus: (
    integrationId: string,
  ) => IntegrationStatus | undefined;
  connectIntegration: (
    integrationId: string,
  ) => Promise<{ status: string; toolsCount?: number }>;
  disconnectIntegration: (integrationId: string) => Promise<void>;
  createCustomIntegration: (
    request: CreateCustomIntegrationRequest,
  ) => Promise<CreateCustomIntegrationResponse>;
  deleteCustomIntegration: (integrationId: string) => Promise<void>;
  publishIntegration: (integrationId: string) => Promise<void>;
  unpublishIntegration: (integrationId: string) => Promise<void>;
  refetch: () => Promise<void>;
}

const EMPTY_INTEGRATIONS: Integration[] = Object.freeze(
  [],
) as Integration[];

const asyncNoop = async (): Promise<void> => {};

export const useFetchIntegrationStatus = (_params?: {
  refetchOnMount?: boolean | "always";
}): {
  data: undefined;
  isLoading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
} => ({
  data: undefined,
  isLoading: false,
  error: null,
  refetch: asyncNoop,
});

export const useIntegrations = (): UseIntegrationsReturn => ({
  integrations: EMPTY_INTEGRATIONS,
  isLoading: false,
  error: null,
  getIntegrationStatus: () => undefined,
  connectIntegration: async () => ({ status: "noop" }),
  disconnectIntegration: asyncNoop,
  createCustomIntegration: async () =>
    ({}) as CreateCustomIntegrationResponse,
  deleteCustomIntegration: asyncNoop,
  publishIntegration: asyncNoop,
  unpublishIntegration: asyncNoop,
  refetch: asyncNoop,
});
