import { Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useState } from "react";

import { SETUP_STEPS, Shell } from "../components/Shell.js";
import {
  EnvSetupSpinnerStep,
  ErrorStep,
  PortConflictStep,
  SystemChecksStep,
} from "../components/shared-steps.js";
import { THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";
import {
  AlternativeGroupSelectionStep,
  DependencyInstallStep,
  EnvConfigStep,
  EnvGroupConfigStep,
  EnvMethodSelectionStep,
  InfisicalSetupStep,
  SetupModeSelectionStep,
} from "./init.js";

export const SetupScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const [state, setState] = useState(store.currentState);

  useEffect(() => {
    const update = () => setState({ ...store.currentState });
    store.on("change", update);
    return () => {
      store.off("change", update);
    };
  }, [store]);

  useInput((_input, key) => {
    if ((key.return || key.escape) && state.error) {
      store.submitInput("exit");
    }
  });

  return (
    <Shell status={state.status} step={state.step} steps={SETUP_STEPS}>
      {state.step === "Detect Repo" && (
        <Box
          flexDirection="column"
          paddingX={2}
          borderStyle="round"
          borderColor={THEME_COLOR}
        >
          <Text bold>Detecting GAIA Repository</Text>
          <Box marginTop={1}>
            <Spinner label="Searching for repository..." />
          </Box>
          {state.data.repoPath && (
            <Box marginTop={1}>
              <Text color="green">Found: {state.data.repoPath}</Text>
            </Box>
          )}
        </Box>
      )}

      {state.step === "Prerequisites" && state.data.checks && (
        <SystemChecksStep checks={state.data.checks} />
      )}

      {state.inputRequest?.id === "port_conflicts" &&
        state.data.portConflicts && (
          <PortConflictStep
            portResults={state.data.portConflicts}
            onAccept={() => store.submitInput("accept")}
            onAbort={() => store.submitInput("abort")}
          />
        )}

      {state.inputRequest?.id === "setup_mode" && (
        <SetupModeSelectionStep onSelect={(mode) => store.submitInput(mode)} />
      )}

      {state.inputRequest?.id === "env_method" && (
        <EnvMethodSelectionStep
          onSelect={(method) => store.submitInput(method)}
        />
      )}

      {state.inputRequest?.id === "env_infisical" && (
        <InfisicalSetupStep onSubmit={(values) => store.submitInput(values)} />
      )}

      {state.step === "Environment Setup" &&
        state.inputRequest?.id === "env_var" &&
        state.data.currentEnvVar && (
          <EnvConfigStep
            categories={state.data.envCategories || []}
            currentVar={state.data.currentEnvVar}
            currentIndex={state.data.envVarIndex || 0}
            totalCount={state.data.envVarTotal || 0}
            onSubmit={(value) => store.submitInput(value)}
            onSkip={() => store.submitInput("")}
          />
        )}

      {state.step === "Environment Setup" &&
        state.inputRequest?.id === "env_group" &&
        state.data.currentEnvGroup && (
          <EnvGroupConfigStep
            category={state.data.currentEnvGroup}
            currentIndex={state.data.envGroupIndex || 0}
            totalGroups={state.data.envGroupTotal || 0}
            onSubmit={(values) => store.submitInput(values)}
          />
        )}

      {state.step === "Environment Setup" &&
        state.inputRequest?.id === "env_alternatives" &&
        state.data.alternativeGroups && (
          <AlternativeGroupSelectionStep
            alternatives={state.data.alternativeGroups}
            onSubmit={(selectedGroups, values) =>
              store.submitInput({ selectedGroups, values })
            }
          />
        )}

      {state.step === "Environment Setup" && !state.inputRequest && (
        <EnvSetupSpinnerStep status={state.status} />
      )}

      {state.step === "Project Setup" && (
        <DependencyInstallStep
          title="Project Setup"
          phase={state.data.dependencyPhase || ""}
          progress={state.data.dependencyProgress || 0}
          isComplete={state.data.dependencyComplete || false}
          logs={state.data.dependencyLogs || []}
        />
      )}

      {state.step === "Finished" && (
        <FinishedStep
          setupMode={state.data.setupMode}
          portOverrides={state.data.portOverrides}
          onConfirm={() => store.submitInput("exit")}
        />
      )}

      {state.error && <ErrorStep message={state.error.message} />}
    </Shell>
  );
};

const FinishedStep: React.FC<{
  setupMode?: string;
  portOverrides?: Record<number, number>;
  onConfirm: () => void;
}> = ({ setupMode, portOverrides, onConfirm }) => {
  useInput((_input, key) => {
    if (key.return) onConfirm();
  });

  const webPort = portOverrides?.[3000] ?? 3000;
  const apiPort = portOverrides?.[8000] ?? 8000;

  return (
    <Box
      flexDirection="column"
      marginTop={2}
      borderStyle="round"
      borderColor={THEME_COLOR}
      padding={1}
    >
      <Text color={THEME_COLOR} bold>
        Setup Complete!
      </Text>

      <Box marginTop={1}>
        <Text bold>Run: </Text>
        <Text color="cyan">
          {setupMode === "selfhost" ? "$ gaia start" : "$ gaia dev"}
        </Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text>
          Web:{" "}
          <Text color="cyan" bold>
            http://localhost:{webPort}
          </Text>
        </Text>
        <Text>
          API:{" "}
          <Text color="cyan" bold>
            http://localhost:{apiPort}
          </Text>
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color="gray">
          {setupMode === "selfhost"
            ? "gaia logs · gaia stop · gaia status · gaia setup"
            : "gaia dev full · gaia logs · gaia stop · gaia status · gaia setup"}
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text dimColor>
          <Text bold>Enter</Text> to exit
        </Text>
      </Box>
    </Box>
  );
};
