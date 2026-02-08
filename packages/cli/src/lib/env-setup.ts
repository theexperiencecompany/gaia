import * as path from "path";
import type { CLIStore } from "../ui/store.js";
import * as envParser from "./env-parser.js";
import * as envWriter from "./env-writer.js";

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export async function runEnvSetup(
  store: CLIStore,
  repoPath: string,
  portOverrides?: Record<number, number>,
): Promise<void> {
  store.setStep("Environment Setup");
  store.setStatus("Configuring environment...");

  const setupMode = (await store.waitForInput(
    "setup_mode",
  )) as envParser.SetupMode;
  store.updateData("setupMode", setupMode);

  store.setStatus("Configuring environment variables...");
  const envMethod = await store.waitForInput("env_method");

  const envValues: Record<string, string> = {};
  envValues["ENV"] = "development";

  const infraVars = envParser.getInfrastructureVariables();
  for (const varName of infraVars) {
    const defaultVal = envParser.getDefaultValue(varName, setupMode);
    if (defaultVal) {
      envValues[varName] = defaultVal;
    }
  }

  if (envMethod === "infisical") {
    await collectInfisicalEnv(store, envValues);
  } else {
    await collectManualEnv(store, repoPath, envValues, setupMode);
  }

  if (portOverrides) {
    envParser.applyPortOverrides(envValues, portOverrides);
  }

  await writeAllEnvFiles(store, repoPath, envValues, setupMode, portOverrides);
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
    store.setError(
      new Error(`Failed to parse settings: ${(e as Error).message}`),
    );
    return;
  }

  const alternativeGroupNames = new Set<string>();
  const alternativePairs: envParser.EnvCategory[][] = [];
  const processedAlternatives = new Set<string>();

  for (const category of categories) {
    if (category.alternativeGroup && !processedAlternatives.has(category.name)) {
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
      selectedGroup: string;
      values: Record<string, string>;
    };

    for (const [key, value] of Object.entries(result.values)) {
      if (value) {
        envValues[key] = value;
      }
    }
  }

  // Auto-apply infrastructure defaults
  const infraVars = envParser.getInfrastructureVariables();
  for (const varName of infraVars) {
    const defaultVal = envParser.getDefaultValue(varName, setupMode);
    if (defaultVal) {
      envValues[varName] = defaultVal;
    }
  }

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

    if (value || envVar.required) {
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
      if (value || varDef?.required) {
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
    store.setError(
      new Error(`Failed to write API .env file: ${(e as Error).message}`),
    );
    return;
  }

  // Write web .env
  store.setStatus("Writing web environment file...");
  try {
    envWriter.writeWebEnvFile(repoPath, setupMode, portOverrides);
    store.setStatus("Web environment variables configured!");
  } catch (e) {
    store.setError(
      new Error(`Failed to write web .env file: ${(e as Error).message}`),
    );
  }
}
