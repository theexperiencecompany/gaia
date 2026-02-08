import { execa } from "execa";
import * as fs from "node:fs";
import * as path from "node:path";

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

const INFRASTRUCTURE_DEFAULTS: Record<SetupMode, Record<string, string>> = {
  selfhost: {
    MONGO_DB: "mongodb://mongo:27017/gaia",
    REDIS_URL: "redis://redis:6379",
    POSTGRES_URL: "postgresql://postgres:postgres@postgres:5432/langgraph", // pragma: allowlist secret
    CHROMADB_HOST: "chromadb",
    CHROMADB_PORT: "8000",
    RABBITMQ_URL: "amqp://guest:guest@rabbitmq:5672/",  // pragma: allowlist secret
    HOST: "http://localhost:8000",
    FRONTEND_URL: "http://localhost:3000",
    GAIA_BACKEND_URL: "http://gaia-backend:80",
  },
  developer: {
    MONGO_DB: "mongodb://localhost:27017/gaia",
    REDIS_URL: "redis://localhost:6379",
    POSTGRES_URL: "postgresql://postgres:postgres@localhost:5432/langgraph",  // pragma: allowlist secret
    CHROMADB_HOST: "localhost",
    CHROMADB_PORT: "8080",
    RABBITMQ_URL: "amqp://guest:guest@localhost:5672/",  // pragma: allowlist secret
    HOST: "http://localhost:8000",
    FRONTEND_URL: "http://localhost:3000",
    GAIA_BACKEND_URL: "http://host.docker.internal:8000",
  },
};

const WEB_INFRASTRUCTURE_DEFAULTS: Record<SetupMode, Record<string, string>> = {
  selfhost: {
    NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
    NEXT_PUBLIC_API_URL: "http://localhost:8000",
    NEXT_PUBLIC_APP_URL: "http://localhost:3000",
    NEXT_PUBLIC_BACKEND_URL: "http://localhost:8000",
    NEXT_PUBLIC_WS_URL: "ws://localhost:8000",
  },
  developer: {
    NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
    NEXT_PUBLIC_API_URL: "http://localhost:8000",
    NEXT_PUBLIC_APP_URL: "http://localhost:3000",
    NEXT_PUBLIC_BACKEND_URL: "http://localhost:8000",
    NEXT_PUBLIC_WS_URL: "ws://localhost:8000",
  },
};

export function getDefaultValue(
  varName: string,
  mode: SetupMode,
): string | undefined {
  return INFRASTRUCTURE_DEFAULTS[mode][varName];
}

export async function parseSettings(
  repoPath: string,
): Promise<EnvCategory[]> {
  const scriptPath = path.join(
    repoPath,
    "apps/api/scripts/dump_config_schema.py",
  );
  const validatorPath = path.join(
    repoPath,
    "apps/api/app/config/settings_validator.py",
  );
  const settingsPath = path.join(
    repoPath,
    "apps/api/app/config/settings.py",
  );

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
  const envPath = path.join(repoPath, "apps", "web", ".env");
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
  mode: SetupMode,
  portOverrides?: Record<number, number>,
): Record<string, string> {
  const defaults = { ...WEB_INFRASTRUCTURE_DEFAULTS[mode] };

  if (portOverrides) {
    const apiPort = portOverrides[8000] || 8000;
    const webPort = portOverrides[3000] || 3000;

    if (apiPort !== 8000) {
      defaults["NEXT_PUBLIC_API_BASE_URL"] = `http://localhost:${apiPort}`;
      defaults["NEXT_PUBLIC_API_URL"] = `http://localhost:${apiPort}`;
      defaults["NEXT_PUBLIC_BACKEND_URL"] = `http://localhost:${apiPort}`;
      defaults["NEXT_PUBLIC_WS_URL"] = `ws://localhost:${apiPort}`;
    }
    if (webPort !== 3000) {
      defaults["NEXT_PUBLIC_APP_URL"] = `http://localhost:${webPort}`;
    }
  }

  return defaults;
}

export function applyPortOverrides(
  envValues: Record<string, string>,
  portOverrides: Record<number, number>,
): void {
  for (const [original, replacement] of Object.entries(portOverrides)) {
    const origPort = Number(original);
    for (const [key, value] of Object.entries(envValues)) {
      if (value.includes(`:${origPort}`)) {
        envValues[key] = value.replace(
          `:${origPort}`,
          `:${replacement}`,
        );
      }
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
