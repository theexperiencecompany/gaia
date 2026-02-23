import * as path from "path";
import type { CLIStore } from "../ui/store.js";
import * as envParser from "./env-parser.js";
import * as envWriter from "./env-writer.js";

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

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
): Promise<void> {
  store.setStep("Environment Setup");
  store.setStatus("Configuring environment...");
  store.updateData("setupMode", setupMode);

  store.setStatus("Configuring environment variables...");
  const envMethod = await store.waitForInput("env_method");
  store.updateData("envMethod", envMethod);

  const envValues: Record<string, string> = {};
  envValues["ENV"] = "development";

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

  if (envMethod === "infisical") {
    await collectInfisicalEnv(store, envValues);
    store.setStatus(
      "Infisical credentials saved. Ensure your Infisical project contains all required variables.",
    );
    // Skip manual env collection - all secrets managed in Infisical
  } else {
    try {
      await collectManualEnv(store, repoPath, envValues, setupMode);
    } catch (e) {
      store.setError(e as Error);
      return;
    }
  }

  if (portOverrides) {
    envParser.applyPortOverrides(envValues, portOverrides, setupMode);
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

async function collectInfisicalEnv(
  store: CLIStore,
  envValues: Record<string, string>,
): Promise<void> {
  store.setStatus("Configuring Infisical...");
  const infisicalConfig = (await store.waitForInput("env_infisical")) as {
    INFISICAL_TOKEN: string;
    INFISICAL_PROJECT_ID: string;
    INFISICAL_MACHINE_IDENTITY_CLIENT_ID: string;
    INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET: string;
  };

  envValues["INFISICAL_TOKEN"] = infisicalConfig.INFISICAL_TOKEN;
  envValues["INFISICAL_PROJECT_ID"] = infisicalConfig.INFISICAL_PROJECT_ID;
  envValues["INFISICAL_MACHINE_IDENTITY_CLIENT_ID"] =
    infisicalConfig.INFISICAL_MACHINE_IDENTITY_CLIENT_ID;
  envValues["INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET"] =
    infisicalConfig.INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET;
}

async function collectManualEnv(
  store: CLIStore,
  repoPath: string,
  envValues: Record<string, string>,
  setupMode: envParser.SetupMode,
): Promise<void> {
  store.setStatus("Parsing environment variables...");
  let categories: envParser.EnvCategory[];
  try {
    categories = await envParser.parseSettings(repoPath);
    categories = envParser.applyModeDefaults(categories, setupMode);
  } catch (e) {
    if (setupMode === "selfhost") {
      throw new Error(
        "Manual environment setup requires Python to parse config schema.\n" +
          "For self-host mode, we recommend using Infisical for secret management.\n" +
          "Alternatively, install Python 3.11+ and try again.\n\n" +
          `Original error: ${(e as Error).message}`,
      );
    }
    throw new Error(`Failed to parse settings: ${(e as Error).message}`);
  }

  const alternativeGroupNames = new Set<string>();
  const alternativePairs: envParser.EnvCategory[][] = [];
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
