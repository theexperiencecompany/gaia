import type {
  ComposioCatalogEntry,
  ComposioIntegrationSetup,
  ComposioToolkitDetailResponse,
} from "@shared/api/generated";
import { api } from "@/lib/api/typed";

export type {
  ComposioCatalogEntry,
  ComposioIntegrationSetup,
  ComposioToolkitDetailResponse,
};

export const COMPOSIO_SETUP_DOCS_URL =
  "https://docs.heygaia.io/self-hosting/composio-integrations";

/** The Settings page where the admin saves the Composio key and enables apps. */
export const COMPOSIO_SETUP_PATH = "/settings/integrations-setup";

export const COMPOSIO_CATALOG_PAGE_SIZE = 50;

export const composioSetupApi = {
  fetchSetup: () => api.get("/api/v1/setup/composio", { silent: true }),

  saveAuthConfigs: (authConfigs: Record<string, string>) =>
    api.put("/api/v1/setup/composio/auth-configs", {
      body: { auth_configs: authConfigs },
    }),

  searchToolkits: (q: string, category: string | null, offset: number) =>
    api.get("/api/v1/setup/composio/toolkits", {
      query: {
        q,
        category,
        offset,
        limit: COMPOSIO_CATALOG_PAGE_SIZE,
      },
      silent: true,
    }),

  fetchToolkit: (slug: string) =>
    api.get("/api/v1/setup/composio/toolkits/{slug}", {
      path: { slug },
      silent: true,
    }),

  enableToolkit: (slug: string, credentials: Record<string, string>) =>
    api.post("/api/v1/setup/composio/toolkits/{slug}", {
      path: { slug },
      body: { credentials },
    }),

  disableToolkit: (slug: string) =>
    api.delete("/api/v1/setup/composio/toolkits/{slug}", { path: { slug } }),
};
