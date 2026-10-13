import type {
  ComposioIntegrationSetup,
  ComposioSetupResponse,
} from "@shared/api/generated";
import { api } from "@/lib/api/typed";

export type { ComposioIntegrationSetup, ComposioSetupResponse };

export const COMPOSIO_SETUP_DOCS_URL =
  "https://docs.heygaia.io/self-hosting/composio-integrations";

export const composioSetupApi = {
  fetchSetup: () => api.get("/api/v1/setup/composio", { silent: true }),

  saveAuthConfigs: (authConfigs: Record<string, string>) =>
    api.put("/api/v1/setup/composio/auth-configs", {
      body: { auth_configs: authConfigs },
    }),
};
