/**
 * What the header reports about this machine's GAIA: whether it answers, its
 * AI provider, and whether a newer release is ready to install.
 * @module ui/header/instance
 */

import type {
  ProviderCatalogResponse,
  ProviderFeature,
  SetupStatusResponse,
} from "@gaia/shared/api/generated";
import {
  DEFAULT_WEB_PORT,
  installWebUrl,
  localApiUrl,
} from "../../lib/endpoints.js";
import {
  readDockerComposePortOverrides,
  readPinnedGaiaVersion,
} from "../../lib/env-writer.js";
import { detectSetupMode, findInstallRoot } from "../../lib/service-starter.js";
import { readSetupEndpoint } from "../../lib/setup-endpoints.js";
import {
  cachedLatestRelease,
  isNewerRelease,
  refreshLatestRelease,
} from "../../lib/update-check.js";
import type { InstanceStatus } from "./render.js";

/** A local instance answers in milliseconds; longer means it is not there, and the header must not wait. */
const PROBE_TIMEOUT_MS = 300;

const CHAT_FEATURE: ProviderFeature = "ai_models";

/** The chat provider serving now, by its catalog name, or null when none is configured. */
function chatProvider(
  status: SetupStatusResponse,
  catalog: ProviderCatalogResponse | null,
): string | null {
  const provider = status.features[CHAT_FEATURE]?.in_use[0];
  if (!provider) return null;
  return catalog?.providers[provider]?.label ?? provider;
}

/** Ask the local instance whether it is up, within PROBE_TIMEOUT_MS. */
export async function probeInstance(): Promise<InstanceStatus> {
  const repoPath = findInstallRoot();
  const mode = repoPath ? await detectSetupMode(repoPath) : null;
  if (!repoPath || !mode) return { running: false, installed: false };
  const overrides = readDockerComposePortOverrides(repoPath);
  const apiUrl = localApiUrl(mode, overrides);
  const [status, catalog] = await Promise.all([
    readSetupEndpoint<SetupStatusResponse>(apiUrl, "status", PROBE_TIMEOUT_MS),
    readSetupEndpoint<ProviderCatalogResponse>(
      apiUrl,
      "catalog",
      PROBE_TIMEOUT_MS,
    ),
  ]);
  if ("detail" in status) return { running: false, installed: true };
  const webPort = overrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  return {
    running: true,
    webUrl: installWebUrl(repoPath, webPort),
    provider: chatProvider(
      status.data,
      "data" in catalog ? catalog.data : null,
    ),
  };
}

/**
 * The newer release with published images, from the cached check; the check
 * itself refreshes in the background so the header never waits on it.
 */
export function availableUpdate(): string | null {
  void refreshLatestRelease();
  const repoPath = findInstallRoot();
  const latest = cachedLatestRelease();
  if (!repoPath || !latest) return null;
  return isNewerRelease(latest, readPinnedGaiaVersion(repoPath))
    ? latest
    : null;
}
