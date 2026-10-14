/**
 * Ink screen for `gaia up`. Reuses the shared step components and renders
 * only the states the up flow drives; all prompts are pre-answered by the
 * values layer except the explicit Docker-install confirmation.
 * @module commands/up/screen
 */

import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import { Shell } from "../../ui/components/Shell.js";
import {
  DockerInstallConfirmStep,
  EnvSetupSpinnerStep,
  ErrorStep,
  PortConflictStep,
  RepositoryProgressStep,
  SystemChecksStep,
} from "../../ui/components/shared-steps.js";
import { THEME_COLOR } from "../../ui/constants.js";
import { DependencyInstallStep } from "../../ui/screens/init.js";
import type { CLIStore } from "../../ui/store.js";
import { codeSandboxSummary, upHeadline } from "./flow.js";

const BUILD_WAIT_HINT =
  "This can take 5-30 min on 4 GB RAM — please do not cancel.";

const UpFinishedStep: React.FC<{
  webUrl: string;
  reachableUrls: string[];
  apiUrl: string;
  noStart: boolean;
  stillStarting: boolean;
  customProviderNote: boolean;
  codeSandbox: boolean;
}> = ({
  webUrl,
  reachableUrls,
  apiUrl,
  noStart,
  stillStarting,
  customProviderNote,
  codeSandbox,
}) => {
  const success = !noStart && !stillStarting;
  return (
    <Box
      flexDirection="column"
      marginTop={2}
      borderStyle="round"
      borderColor={success ? "green" : THEME_COLOR}
      padding={1}
    >
      <Text bold color={success ? "green" : THEME_COLOR}>
        {upHeadline({ noStart, stillStarting })}
      </Text>

      {success && (
        <Box marginTop={1}>
          <Text color="green">✓ All services started</Text>
        </Box>
      )}

      {stillStarting && (
        <Box marginTop={1} flexDirection="column">
          <Text>
            Containers are up but not answering yet — they are still
            initializing.
          </Text>
          <Text>
            Run{" "}
            <Text color="cyan" bold>
              gaia status
            </Text>{" "}
            to check progress. Services keep running.
          </Text>
        </Box>
      )}

      <Box marginTop={1} flexDirection="column">
        <Text>Open GAIA at:</Text>
        {reachableUrls.map((url) => (
          <Text key={url} color="cyan" bold>
            {"  "}
            {url}
          </Text>
        ))}
        <Text>
          API:{" "}
          <Text color="cyan" bold>
            {apiUrl}
          </Text>
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text>
          Finish setup in your browser:{" "}
          <Text color="cyan" bold underline>
            {webUrl}/setup
          </Text>
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color="gray">{codeSandboxSummary(codeSandbox)}</Text>
      </Box>

      {customProviderNote && (
        <Box marginTop={1}>
          <Text color="gray">
            Custom LLM providers are configured in the setup wizard.
          </Text>
        </Box>
      )}

      {noStart && (
        <Box marginTop={1}>
          <Text color="gray">Start services later with 'gaia start'.</Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text color="gray">
          Run 'gaia doctor' anytime · gaia logs · gaia stop · gaia status
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

export const UpScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
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

  const dependencyPhase = state.data.dependencyPhase || "";
  const showDependencyStep =
    (state.step === "Project Setup" || state.step === "Finished") &&
    !state.data.finished &&
    dependencyPhase !== "";

  return (
    <Shell status={state.status} step={state.step}>
      {state.step === "Prerequisites" && state.data.checks && (
        <SystemChecksStep checks={state.data.checks} />
      )}

      {state.inputRequest?.id === "docker_install_confirm" && (
        <DockerInstallConfirmStep
          onConfirm={() => store.submitInput("install")}
          onDecline={() => store.submitInput("decline")}
        />
      )}

      {state.inputRequest?.id === "port_conflicts" &&
        state.data.portConflicts && (
          <PortConflictStep
            portResults={state.data.portConflicts}
            onAccept={() => store.submitInput("accept")}
            onAbort={() => store.submitInput("abort")}
          />
        )}

      {state.step === "Repository Setup" && !state.inputRequest && (
        <RepositoryProgressStep
          title="Setting Up Repository"
          progress={state.data.repoProgress}
          phase={state.data.repoPhase}
        />
      )}

      {state.step === "Environment Setup" && !state.inputRequest && (
        <EnvSetupSpinnerStep status={state.status} />
      )}

      {showDependencyStep && (
        <DependencyInstallStep
          title="Starting GAIA"
          phase={dependencyPhase}
          progress={state.data.dependencyProgress || 0}
          isComplete={state.data.dependencyComplete || false}
          logs={state.data.dependencyLogs}
          hint={
            dependencyPhase.toLowerCase().includes("building")
              ? BUILD_WAIT_HINT
              : undefined
          }
        />
      )}

      {state.step === "Finished" && state.data.finished && (
        <UpFinishedStep
          webUrl={state.data.upWebUrl}
          reachableUrls={state.data.upReachableUrls}
          apiUrl={state.data.upApiUrl}
          noStart={state.data.upNoStart === true}
          stillStarting={
            state.data.upNoStart !== true && state.data.upStillStarting === true
          }
          customProviderNote={state.data.customProviderNote === true}
          codeSandbox={state.data.upCodeSandbox === true}
        />
      )}

      {state.error && <ErrorStep message={state.error.message} />}
    </Shell>
  );
};
