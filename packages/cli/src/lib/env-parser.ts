import * as fs from "node:fs";
import * as path from "node:path";
import { execa } from "execa";

export type SetupMode = "selfhost" | "developer";

export interface EnvVar {
  name: string;
  required: boolean;
  category: string;
  description: string;
  affectedFeatures: string;
  defaultValue?: string;
  docsUrl?: string;
}

export interface EnvCategory {
  name: string;
  description: string;
  affectedFeatures: string;
  requiredInProd: boolean;
  allRequired: boolean;
  docsUrl?: string;
  alternativeGroup?: string;
  variables: EnvVar[];
}

export interface WebEnvVar {
  name: string;
  value: string;
  category: string;
}

// Infrastructure connection strings set by setup mode.
//
// selfhost: API runs inside Docker; database URLs use container hostnames
//   (e.g. "mongo", "redis") which resolve within Docker's internal network.
//   CHROMADB_PORT=8000 is the container-internal port. The host maps it to
//   8080 via docker-compose (8080:8000). healthcheck.ts always probes 8080
//   on the host — that is correct and does NOT use this env var.
//
// developer: Everything runs on localhost. CHROMADB_PORT=8080 is the
//   host-mapped port exposed by docker-compose for local use.
const INFRASTRUCTURE_DEFAULTS: Record<SetupMode, Record<string, string>> = {
  selfhost: {
    MONGO_DB: "mongodb://mongo:27017/gaia",
    REDIS_URL: "redis://redis:6379",
    POSTGRES_URL: "postgresql://postgres:postgres@postgres:5432/langgraph", // pragma: allowlist secret
    CHROMADB_HOST: "chromadb", // Docker container hostname (internal network)
    CHROMADB_PORT: "8000", // Container-internal port; host maps 8080→8000
    RABBITMQ_URL: "amqp://guest:guest@rabbitmq:5672/", // pragma: allowlist secret
  },
  developer: {
    MONGO_DB: "mongodb://localhost:27017/gaia",
    REDIS_URL: "redis://localhost:6379",
    POSTGRES_URL: "postgresql://postgres:postgres@localhost:5432/postgres", // pragma: allowlist secret
    CHROMADB_HOST: "localhost",
    CHROMADB_PORT: "8080", // Host-mapped port from docker-compose (8080:8000)
    RABBITMQ_URL: "amqp://guest:guest@localhost:5672/", // pragma: allowlist secret
  },
};

// Deployment / routing URLs — not infrastructure, users may want to customize.
// GAIA_BACKEND_URL is voice-agent-only (how the voice container reaches the API).
// SETUP_MODE is a marker for robust mode detection (replaces fragile string matching).
const DEPLOYMENT_DEFAULTS: Record<SetupMode, Record<string, string>> = {
  selfhost: {
    HOST: "http://localhost:8000",
    FRONTEND_URL: "http://localhost:3000",
    GAIA_BACKEND_URL: "http://gaia-backend:80",
    SETUP_MODE: "selfhost",
  },
  developer: {
    HOST: "http://localhost:8000",
    FRONTEND_URL: "http://localhost:3000",
    GAIA_BACKEND_URL: "http://host.docker.internal:8000",
    SETUP_MODE: "developer",
  },
};

export function getDefaultValue(
  varName: string,
  mode: SetupMode,
): string | undefined {
  return (
    INFRASTRUCTURE_DEFAULTS[mode][varName] ?? DEPLOYMENT_DEFAULTS[mode][varName]
  );
}

export async function parseSettings(repoPath: string): Promise<EnvCategory[]> {
  const scriptPath = path.join(
    repoPath,
    "apps/api/scripts/dump_config_schema.py",
  );
  const validatorPath = path.join(
    repoPath,
    "apps/api/app/config/settings_validator.py",
  );
  const settingsPath = path.join(repoPath, "apps/api/app/config/settings.py");

  if (!fs.existsSync(scriptPath)) {
    throw new Error("dump_config_schema.py not found in apps/api/scripts");
  }

  try {
    try {
      const { stdout } = await execa(
        "python3",
        [scriptPath, validatorPath, settingsPath],
        { cwd: repoPath },
      );
      return JSON.parse(stdout);
    } catch {
      const { stdout } = await execa(
        "python",
        [scriptPath, validatorPath, settingsPath],
        { cwd: repoPath },
      );
      return JSON.parse(stdout);
    }
  } catch (e) {
    throw new Error(
      `Failed to parse settings schema: ${(e as Error).message}. Ensure python is installed.`,
    );
  }
}

export function parseWebEnv(repoPath: string): WebEnvVar[] {
  const envLocalPath = path.join(repoPath, "apps", "web", ".env.local");
  const envPath = fs.existsSync(envLocalPath)
    ? envLocalPath
    : path.join(repoPath, "apps", "web", ".env");
  if (!fs.existsSync(envPath)) return [];

  const content = fs.readFileSync(envPath, "utf-8");
  const vars: WebEnvVar[] = [];
  let currentCategory = "General";

  for (const line of content.split("\n")) {
    const trimmed = line.trim();

    // Parse comment groups as categories
    if (trimmed.startsWith("#") && !trimmed.startsWith("#=")) {
      const categoryName = trimmed.replace(/^#+\s*/, "").trim();
      if (categoryName && !categoryName.startsWith("These are")) {
        currentCategory = categoryName;
      }
      continue;
    }

    if (!trimmed || trimmed.startsWith("#")) continue;

    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;

    const name = trimmed.substring(0, eqIdx).trim();
    const value = trimmed.substring(eqIdx + 1).trim();

    vars.push({ name, value, category: currentCategory });
  }

  return vars;
}

export function getWebInfrastructureDefaults(
  _mode: SetupMode,
  portOverrides?: Record<number, number>,
): Record<string, string> {
  const apiPort = portOverrides?.[8000] ?? 8000;

  // Single env var for the web app. WS URLs are derived from this at runtime
  // by swapping http:// -> ws:// (see useWebSocketConnection.ts).
  // Always uses localhost because this is a browser-side (client) URL —
  // even in selfhost mode the browser connects via Docker-mapped host ports.
  return {
    NEXT_PUBLIC_API_BASE_URL: `http://localhost:${apiPort}/api/v1/`,
  };
}

export function applyPortOverrides(
  envValues: Record<string, string>,
  portOverrides: Record<number, number>,
  setupMode?: SetupMode,
): void {
  // In selfhost mode, infrastructure variables use Docker-internal addresses
  // and container-internal ports (e.g., postgres:5432). These must NOT be
  // rewritten — only the host port mapping changes, not the internal port.
  const skipKeys =
    setupMode === "selfhost"
      ? new Set(Object.keys(INFRASTRUCTURE_DEFAULTS.selfhost))
      : new Set<string>();

  for (const [original, replacement] of Object.entries(portOverrides)) {
    const origPort = Number(original);
    const newPort = Number(replacement);
    for (const [key, value] of Object.entries(envValues)) {
      if (skipKeys.has(key)) continue;

      // Handle bare port values (e.g., CHROMADB_PORT=8080)
      if (value === String(origPort)) {
        envValues[key] = String(newPort);
        continue;
      }

      // Handle port in URL context (e.g., :5432/ or :5432 at end)
      const portPattern = new RegExp(`:${origPort}(?=[/\\s]|$)`, "g");
      envValues[key] = value.replaceAll(portPattern, `:${newPort}`);
    }
  }
}

export function getCoreVariables(categories: EnvCategory[]): EnvVar[] {
  const coreGroupNames = [
    "MongoDB Connection",
    "Redis Connection",
    "PostgreSQL Connection",
    "RabbitMQ Connection",
    "WorkOS Authentication",
  ];

  return categories
    .filter((c) => coreGroupNames.includes(c.name))
    .flatMap((c) => c.variables);
}

export function applyModeDefaults(
  categories: EnvCategory[],
  mode: SetupMode,
): EnvCategory[] {
  return categories.map((category) => ({
    ...category,
    variables: category.variables.map((variable) => {
      const modeDefault = getDefaultValue(variable.name, mode);
      return {
        ...variable,
        defaultValue: modeDefault || variable.defaultValue,
      };
    }),
  }));
}

export function getInfrastructureVariables(): string[] {
  return Object.keys(INFRASTRUCTURE_DEFAULTS.selfhost);
}

export function getDeploymentVariables(): string[] {
  return Object.keys(DEPLOYMENT_DEFAULTS.selfhost);
}

export function getDeploymentDefaults(mode: SetupMode): Record<string, string> {
  return { ...DEPLOYMENT_DEFAULTS[mode] };
}

export function getAlternativeGroups(
  categories: EnvCategory[],
): Map<string, string> {
  const alternatives = new Map<string, string>();
  for (const category of categories) {
    if (category.alternativeGroup) {
      alternatives.set(category.name, category.alternativeGroup);
    }
  }
  return alternatives;
}

export function isCategorySatisfied(
  categoryName: string,
  configuredCategories: Set<string>,
  alternatives: Map<string, string>,
): boolean {
  if (configuredCategories.has(categoryName)) {
    return true;
  }
  const alternative = alternatives.get(categoryName);
  return alternative ? configuredCategories.has(alternative) : false;
}
