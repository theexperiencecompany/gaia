/**
 * Runtime provider-credential endpoints — `/setup/status`, `/setup/catalog`,
 * `/setup/providers` (+ `/{provider}/test`).
 *
 * The `/setup` router mounts on EVERY deployment (the wizard's status probe and
 * catalog are read pre-auth in local mode), so `api.post` and friends DO have
 * `paths` entries generated from `openapi.json` — but the response shapes are
 * assembled per-request from the live credential collection, so the generated
 * types are narrower than what the instance actually answers. The typed client
 * therefore cannot express these without hand-maintaining a twin of the schema,
 * which the `api-schema-types` gate forbids outright.
 *
 * So the transport lives here, inside `lib/api`, where the axios instances are
 * sanctioned, and feature code imports the small typed surface below from
 * `features/settings/api/providersApi`. Same arrangement as `localAuth.ts`.
 */

import { apiauth } from "./client";
import type {
  CredentialProvider,
  ProviderConfigBody,
  ProviderTestResult,
  StoredProviderConfig,
} from "./setupTransport.types";

export type {
  CredentialProvider,
  ProviderConfigBody,
  ProviderTestResult,
  StoredProviderConfig,
};

const setupUrl = (path: string): string => `${apiauth.getUri()}setup/${path}`;

export const setupTransport = {
  async get<T>(path: string): Promise<T> {
    const response = await apiauth.get<T>(setupUrl(path));
    return response.data;
  },

  async put<T>(path: string, body: ProviderConfigBody): Promise<T> {
    const response = await apiauth.put<T>(setupUrl(path), body);
    return response.data;
  },

  async post<T>(
    path: string,
    body: ProviderConfigBody | Record<string, string> = {},
  ): Promise<T> {
    const response = await apiauth.post<T>(setupUrl(path), body);
    return response.data;
  },

  async delete(path: string): Promise<void> {
    await apiauth.delete(setupUrl(path));
  },
};
