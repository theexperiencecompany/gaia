import * as fs from "node:fs";
import * as path from "node:path";
import type { CLIStore } from "../ui/store.js";
import { getDockerSocketGid } from "./docker.js";
import * as envParser from "./env-parser.js";
import * as envWriter from "./env-writer.js";
import { apiEnvPath, detectSetupMode } from "./install-root.js";
import type { LlmProvider } from "./llm-flags.js";
import { collectMachineSecrets } from "./machine-secrets.js";

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export interface EnvSetupOptions {
  /** Provider selected via `gaia up --llm-provider`. */
  llmProvider?: LlmProvider;
  /** Public domain from `gaia up --domain`; GAIA is served at https://<domain>. False on --no-domain. */
  domain?: envWriter.DomainFlag;
}

export async function selectSetupMode(
  store: CLIStore,
): Promise<envParser.SetupMode> {
  store.setStep("Setup Mode");
  store.setStatus("Choose how to run GAIA…");
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
  store.setStatus("Configuring GAIA…");
  store.updateData("setupMode", setupMode);

  store.setStatus("Configuring GAIA…");
  const envMethod = await store.waitForInput("env_method");
  store.updateData("envMethod", envMethod);

  // ENV policy: self-host instances run as the first-class selfhost tier with
  // local email/password auth; developer checkouts keep development (WorkOS).
  const defaults: Record<string, string> = {
    ENV: setupMode === "selfhost" ? "selfhost" : "development",
  };
  if (setupMode === "selfhost") {
    defaults["AUTH_MODE"] = "local";
  }
  for (const varName of envParser.getInfrastructureVariables()) {
    const defaultVal = envParser.getDefaultValue(varName, setupMode);
    if (defaultVal) {
      defaults[varName] = defaultVal;
    }
  }
  Object.assign(defaults, envParser.getDeploymentDefaults(setupMode));

  // What this run was told: flags and wizard answers.
  const answers: Record<string, string> = {};
  if (options?.domain) {
    // Links in emails and OAuth callbacks must name the public origin.
    answers["HOST"] = `https://${options.domain}`;
    answers["FRONTEND_URL"] = `https://${options.domain}`;
  } else if (options?.domain === false) {
    // Back to the plain origin a domain-less install has, before port overrides apply.
    for (const key of ["HOST", "FRONTEND_URL"]) {
      const value = defaults[key];
      if (value) answers[key] = value;
    }
  }

  if (envMethod === "infisical") {
    await collectInfisicalEnv(store, answers);
    store.setStatus(
      "Infisical credentials saved. Ensure your Infisical project contains all required variables.",
    );
    // Skip manual env collection - all secrets managed in Infisical
  } else {
    // The schema is vendored (see env-parser.loadVendoredSchema), so manual
    // collection never depends on a host Python install. Load failures
    // propagate — the caller surfaces them.
    await collectManualEnv(
      store,
      answers,
      setupMode,
      // --llm-provider already chose one; asking again would offer a different pick.
      options?.llmProvider === undefined,
    );
  }

  const existingEnv = fs.existsSync(apiEnvPath(repoPath))
    ? fs.readFileSync(apiEnvPath(repoPath), "utf-8")
    : null;
  const envValues = mergeEnvLayers({
    defaults,
    existing: envWriter.parseEnvFileValues(existingEnv),
    existingMode: await detectSetupMode(repoPath),
    answers,
    setupMode,
  });
  if (portOverrides) {
    envParser.applyPortOverrides(envValues, portOverrides, setupMode);
  }
  if (setupMode === "selfhost") {
    // Generated only for still-missing secrets; existing ones are kept.
    Object.assign(envValues, collectMachineSecrets(existingEnv));
  }

  try {
    await writeAllEnvFiles(
      store,
      repoPath,
      envValues,
      setupMode,
      portOverrides,
      options?.domain,
    );
  } catch (e) {
    store.setError(e as Error);
    return;
  }
  await delay(1000);
}

/**
 * Layer one setup run's values: a rerun of the same mode keeps every value the
 * user edited in apps/api/.env over the computed defaults, and only this run's
 * flags and answers replace them. Switching mode takes the new mode's defaults
 * (the old mode's infra addresses would not resolve). SETUP_MODE is the CLI's.
 */
function mergeEnvLayers(layers: {
  defaults: Record<string, string>;
  existing: Record<string, string>;
  existingMode: envParser.SetupMode | null;
  answers: Record<string, string>;
  setupMode: envParser.SetupMode;
}): Record<string, string> {
  const { defaults, existing, existingMode, answers, setupMode } = layers;
  const sameMode = existingMode === setupMode;
  return {
    ...(sameMode ? defaults : existing),
    ...(sameMode ? existing : defaults),
    ...answers,
    SETUP_MODE: setupMode,
  };
}

/**
 * Seed env values from `gaia up --llm-key/--llm-provider` so the flagged
 * provider works on first boot. "custom" providers are runtime-configured via
 * the web wizard — no key is written here; the up flow prints the wizard URL
 * after boot instead.
 */
async function collectInfisicalEnv(
  store: CLIStore,
  envValues: Record<string, string>,
): Promise<void> {
  store.setStatus("Configuring Infisical…");
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

  const categoriesByName = new Map(categories.map((c) => [c.name, c]));
  for (const category of categories) {
    if (
      category.alternativeGroup &&
      !processedAlternatives.has(category.name)
    ) {
      const alternative = categoriesByName.get(category.alternativeGroup);
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
  askForProvider: boolean,
): Promise<void> {
  store.setStatus("Parsing environment variables…");
  const categories = envParser
    .applyModeDefaults(envParser.loadVendoredSchema(), setupMode)
    .filter((category) => setupMode !== "selfhost" || category.selfhostSetup);

  const { alternativePairs, alternativeGroupNames } =
    pairAlternativeGroups(categories);

  const singleVarGroups = categories.filter(
    (c) => c.variables.length === 1 && !alternativeGroupNames.has(c.name),
  );
  const multiVarGroups = categories.filter(
    (c) => c.variables.length > 1 && !alternativeGroupNames.has(c.name),
  );

  // Handle alternative groups
  for (const alternatives of askForProvider ? alternativePairs : []) {
    store.updateData("alternativeGroups", alternatives);
    const result = (await store.ask(
      "env_alternatives",
      "Choose an AI provider…",
    )) as {
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
  const infraVars = new Set(envParser.getInfrastructureVariables());

  // Handle single-variable groups
  const singleVars = singleVarGroups
    .flatMap((c) => c.variables)
    .filter((v) => !infraVars.has(v.name));
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
    const value = (await store.ask("env_var", `Configuring ${envVar.name}…`, {
      varName: envVar.name,
    })) as string;

    if (value || envVar.required || envVar.defaultValue) {
      envValues[envVar.name] = value || envVar.defaultValue || "";
    }
  }

  // Handle multi-variable groups
  const sortedMultiVarGroups = [...multiVarGroups]
    .filter((g) => !g.variables.every((v) => infraVars.has(v.name)))
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
    const groupValues = (await store.ask(
      "env_group",
      `Configuring ${group.name}…`,
      { groupName: group.name },
    )) as Record<string, string>;

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
  domain?: envWriter.DomainFlag,
): Promise<void> {
  // Write API .env
  store.setStatus("Saving GAIA's settings…");
  try {
    const apiEnvPath = path.join(repoPath, "apps", "api");
    envWriter.writeEnvFile(apiEnvPath, envValues);
    store.setStatus("Saved GAIA's settings");
  } catch (e) {
    throw new Error(`Failed to write API .env file: ${(e as Error).message}`);
  }

  if (setupMode === "selfhost") {
    store.setStatus("Saving Docker's settings…");
    try {
      envWriter.writeDockerComposeEnv(
        repoPath,
        portOverrides ?? {},
        setupMode,
        {
          dockerSocketGid: getDockerSocketGid(),
          domain,
        },
      );
      store.setStatus("Saved Docker's settings");
    } catch (e) {
      throw new Error(
        `Failed to write Docker Compose .env: ${(e as Error).message}`,
      );
    }
    // The self-host web image is prebuilt and same-origin; apps/web env
    // files only feed the developer dev server.
    return;
  }

  // Write web .env
  store.setStatus("Saving the web app's settings…");
  try {
    envWriter.writeWebEnvFile(repoPath, setupMode, portOverrides);
    store.setStatus("Saved the web app's settings");
  } catch (e) {
    throw new Error(`Failed to write web .env file: ${(e as Error).message}`);
  }

  // Write Docker Compose .env for port overrides
  if (portOverrides && Object.keys(portOverrides).length > 0) {
    store.setStatus("Saving Docker's settings…");
    try {
      // Patch docker-compose.yml to use variable substitution for ports.
      // Older versions of the compose file have hardcoded ports, so the
      // .env override only works after patching.
      envWriter.patchDockerComposePorts(repoPath);
      envWriter.writeDockerComposeEnv(repoPath, portOverrides, setupMode);
      store.setStatus("Saved Docker's settings");
    } catch (e) {
      throw new Error(
        `Failed to write Docker Compose .env: ${(e as Error).message}`,
      );
    }
  }
}
