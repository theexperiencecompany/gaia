import * as fs from "node:fs";
import * as path from "node:path";
import type { CLIStore } from "../ui/store.js";
import * as envParser from "./env-parser.js";
import * as envWriter from "./env-writer.js";
import { collectMachineSecrets } from "./machine-secrets.js";

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export interface EnvSetupOptions {
  /** Provider selected via `gaia up --llm-provider`. */
  llmProvider?: "openrouter" | "gemini" | "custom";
  /** API key supplied via `gaia up --llm-key`. */
  llmKey?: string;
}

export async function selectSetupMode(
  store: CLIStore,
): Promise<envParser.SetupMode> {
  store.setStep("Setup Mode");
  store.setStatus("Choose how to run GAIA...");
  const setupMode = (await store.waitForInput(
    "setup_mode",
  )) as envParser.SetupMode;
  store.updateData("setupMode", setupMode);
  return setupMode;
}

export async function runEnvSetup(
  store: CLIStore,
  repoPath: string,
  setupMode: envParser.SetupMode,
  portOverrides?: Record<number, number>,
  options?: EnvSetupOptions,
): Promise<void> {
  store.setStep("Environment Setup");
  store.setStatus("Configuring environment...");
  store.updateData("setupMode", setupMode);

  store.setStatus("Configuring environment variables...");
  const envMethod = await store.waitForInput("env_method");
  store.updateData("envMethod", envMethod);

  const envValues: Record<string, string> = {};

  // ENV policy: self-host instances run as the first-class selfhost tier with
  // local email/password auth; developer checkouts keep development (WorkOS).
  envValues["ENV"] = setupMode === "selfhost" ? "selfhost" : "development";
  if (setupMode === "selfhost") {
    envValues["AUTH_MODE"] = "local";
  }

  const infraVars = envParser.getInfrastructureVariables();
  for (const varName of infraVars) {
    const defaultVal = envParser.getDefaultValue(varName, setupMode);
    if (defaultVal) {
      envValues[varName] = defaultVal;
    }
  }

  // Add deployment defaults (HOST, FRONTEND_URL, GAIA_BACKEND_URL, SETUP_MODE)
  const deploymentDefaults = envParser.getDeploymentDefaults(setupMode);
  for (const [key, value] of Object.entries(deploymentDefaults)) {
    envValues[key] = value;
  }

  applyLlmFlagAnswers(envValues, options);

  if (envMethod === "infisical") {
    await collectInfisicalEnv(store, envValues);
    store.setStatus(
      "Infisical credentials saved. Ensure your Infisical project contains all required variables.",
    );
    // Skip manual env collection - all secrets managed in Infisical
  } else {
    // The schema is vendored (see env-parser.loadVendoredSchema), so manual
    // collection never depends on a host Python install. Load failures
    // propagate — the caller surfaces them.
    await collectManualEnv(store, envValues, setupMode);
  }

  if (portOverrides) {
    envParser.applyPortOverrides(envValues, portOverrides, setupMode);
  }

  // Merge-don't-clobber against an existing apps/api/.env: previously
  // assigned values (hand-edited or from an earlier run) are carried forward
  // wherever this run didn't compute a fresh value. Machine secrets are then
  // generated only for the trio members still missing — writeEnvFile keeps
  // the .bak backup behavior for pre-existing files.
  const apiEnvPath = path.join(repoPath, "apps", "api", ".env");
  const existingEnv = fs.existsSync(apiEnvPath)
    ? fs.readFileSync(apiEnvPath, "utf-8")
    : null;
  if (existingEnv) {
    for (const [name, value] of Object.entries(
      envWriter.parseEnvFileValues(existingEnv),
    )) {
      if (!(name in envValues)) {
        envValues[name] = value;
      }
    }
  }
  if (setupMode === "selfhost") {
    for (const [name, value] of Object.entries(
      collectMachineSecrets(existingEnv),
    )) {
      envValues[name] = value;
    }
  }

  try {
    await writeAllEnvFiles(
      store,
      repoPath,
      envValues,
      setupMode,
      portOverrides,
    );
  } catch (e) {
    store.setError(e as Error);
    return;
  }
  await delay(1000);
}

/**
 * Seed env values from `gaia up --llm-key/--llm-provider` so the flagged
 * provider works on first boot. "custom" providers are runtime-configured via
 * the web wizard — no key is written here; the up flow prints the wizard URL
 * after boot instead.
 */
function applyLlmFlagAnswers(
  envValues: Record<string, string>,
  options?: EnvSetupOptions,
): void {
  if (!options?.llmKey) return;
  if (options.llmProvider === "openrouter") {
    envValues["OPENROUTER_API_KEY"] = options.llmKey;
  } else if (options.llmProvider === "gemini") {
    envValues["GOOGLE_API_KEY"] = options.llmKey;
  }
}

async function collectInfisicalEnv(
  store: CLIStore,
  envValues: Record<string, string>,
): Promise<void> {
  store.setStatus("Configuring Infisical...");
  const infisicalConfig = (await store.waitForInput("env_infisical")) as {
    INFISICAL_PROJECT_ID: string;
    INFISICAL_MACHINE_IDENTITY_CLIENT_ID: string;
    INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET: string;
  };

  envValues["INFISICAL_PROJECT_ID"] = infisicalConfig.INFISICAL_PROJECT_ID;
  envValues["INFISICAL_MACHINE_IDENTITY_CLIENT_ID"] =
    infisicalConfig.INFISICAL_MACHINE_IDENTITY_CLIENT_ID;
  envValues["INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET"] =
    infisicalConfig.INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET;
}

/** Pairs categories that are alternatives of each other (e.g. OpenRouter vs
 * Gemini — configure either one) and marks both sides as handled. */
function pairAlternativeGroups(categories: envParser.EnvCategory[]): {
  alternativePairs: envParser.EnvCategory[][];
  alternativeGroupNames: Set<string>;
} {
  const alternativePairs: envParser.EnvCategory[][] = [];
  const alternativeGroupNames = new Set<string>();
  const processedAlternatives = new Set<string>();

  for (const category of categories) {
    if (
      category.alternativeGroup &&
      !processedAlternatives.has(category.name)
    ) {
      const alternative = categories.find(
        (c) => c.name === category.alternativeGroup,
      );
      if (alternative) {
        alternativePairs.push([category, alternative]);
        alternativeGroupNames.add(category.name);
        alternativeGroupNames.add(alternative.name);
        processedAlternatives.add(category.name);
        processedAlternatives.add(alternative.name);
      }
    }
  }
  return { alternativePairs, alternativeGroupNames };
}

async function collectManualEnv(
  store: CLIStore,
  envValues: Record<string, string>,
  setupMode: envParser.SetupMode,
): Promise<void> {
  store.setStatus("Parsing environment variables...");
  const categories = envParser.applyModeDefaults(
    envParser.loadVendoredSchema(),
    setupMode,
  );

  const { alternativePairs, alternativeGroupNames } =
    pairAlternativeGroups(categories);

  const singleVarGroups = categories.filter(
    (c) => c.variables.length === 1 && !alternativeGroupNames.has(c.name),
  );
  const multiVarGroups = categories.filter(
    (c) => c.variables.length > 1 && !alternativeGroupNames.has(c.name),
  );

  // Handle alternative groups
  for (const alternatives of alternativePairs) {
    store.updateData("alternativeGroups", alternatives);
    store.setStatus("Choose an AI provider...");

    const result = (await store.waitForInput("env_alternatives")) as {
      selectedGroups: string[];
      values: Record<string, string>;
    };

    for (const [key, value] of Object.entries(result.values)) {
      if (value) {
        envValues[key] = value;
      }
    }
  }

  // Infrastructure vars are already applied in runEnvSetup — skip them in user prompts.
  const infraVars = envParser.getInfrastructureVariables();

  // Handle single-variable groups
  const singleVars = singleVarGroups
    .flatMap((c) => c.variables)
    .filter((v) => !infraVars.includes(v.name));
  const sortedSingleVars = [...singleVars].sort((a, b) => {
    if (a.required && !b.required) return -1;
    if (!a.required && b.required) return 1;
    return 0;
  });

  store.updateData("envVarTotal", sortedSingleVars.length);

  for (let i = 0; i < sortedSingleVars.length; i++) {
    const envVar = sortedSingleVars[i];
    if (!envVar) continue;

    store.updateData("currentEnvVar", envVar);
    store.updateData("envVarIndex", i);
    store.setStatus(`Configuring ${envVar.name}...`);

    const value = (await store.waitForInput("env_var", {
      varName: envVar.name,
    })) as string;

    if (value || envVar.required || envVar.defaultValue) {
      envValues[envVar.name] = value || envVar.defaultValue || "";
    }
  }

  // Handle multi-variable groups
  const sortedMultiVarGroups = [...multiVarGroups]
    .filter((g) => !g.variables.every((v) => infraVars.includes(v.name)))
    .sort((a, b) => {
      const aHasRequired = a.variables.some((v) => v.required);
      const bHasRequired = b.variables.some((v) => v.required);
      if (aHasRequired && !bHasRequired) return -1;
      if (!aHasRequired && bHasRequired) return 1;
      return 0;
    });

  store.updateData("envGroupTotal", sortedMultiVarGroups.length);

  for (let i = 0; i < sortedMultiVarGroups.length; i++) {
    const group = sortedMultiVarGroups[i];
    if (!group) continue;

    store.updateData("currentEnvGroup", group);
    store.updateData("envGroupIndex", i);
    store.setStatus(`Configuring ${group.name}...`);

    const groupValues = (await store.waitForInput("env_group", {
      groupName: group.name,
    })) as Record<string, string>;

    for (const [key, value] of Object.entries(groupValues)) {
      const varDef = group.variables.find((v) => v.name === key);
      if (value || varDef?.required || varDef?.defaultValue) {
        envValues[key] = value || varDef?.defaultValue || "";
      }
    }
  }
}

async function writeAllEnvFiles(
  store: CLIStore,
  repoPath: string,
  envValues: Record<string, string>,
  setupMode: envParser.SetupMode,
  portOverrides?: Record<number, number>,
): Promise<void> {
  // Write API .env
  store.setStatus("Writing API environment file...");
  try {
    const apiEnvPath = path.join(repoPath, "apps", "api");
    envWriter.writeEnvFile(apiEnvPath, envValues);
    store.setStatus("API environment variables configured!");
  } catch (e) {
    throw new Error(`Failed to write API .env file: ${(e as Error).message}`);
  }

  // Write web .env
  store.setStatus("Writing web environment file...");
  try {
    envWriter.writeWebEnvFile(repoPath, setupMode, portOverrides);
    store.setStatus("Web environment variables configured!");
  } catch (e) {
    throw new Error(`Failed to write web .env file: ${(e as Error).message}`);
  }

  // Write Docker Compose .env for port overrides and selfhost build args
  const hasPortOverrides =
    portOverrides && Object.keys(portOverrides).length > 0;
  if (hasPortOverrides || setupMode === "selfhost") {
    store.setStatus("Writing Docker Compose environment...");
    try {
      if (hasPortOverrides) {
        // Patch docker-compose.yml to use variable substitution for ports.
        // Older versions of the compose file have hardcoded ports, so the
        // .env override only works after patching.
        envWriter.patchDockerComposePorts(repoPath);
      }
      envWriter.writeDockerComposeEnv(repoPath, portOverrides ?? {}, setupMode);
      store.setStatus("Docker Compose environment configured!");
    } catch (e) {
      throw new Error(
        `Failed to write Docker Compose .env: ${(e as Error).message}`,
      );
    }
  }
}
