/**
 * Ink screen for `gaia up`. Reuses the shared step components and renders
 * only the states the up flow drives; all prompts are pre-answered by the
 * values layer except the explicit Docker-install confirmation.
 * @module commands/up/screen
 */

import { Box, Text } from "ink";
import type React from "react";
import { Shell, UP_STEPS } from "../../ui/components/Shell.js";
import {
  EnvSetupSpinnerStep,
  ErrorStep,
  InstallConfirmStep,
  PortConflictStep,
  RepositoryProgressStep,
  SystemChecksStep,
} from "../../ui/components/shared-steps.js";
import { BOX_BORDER, THEME_COLOR } from "../../ui/constants.js";
import { DependencyInstallStep } from "../../ui/screens/init.js";
import type { CLIState, CLIStore } from "../../ui/store.js";
import { useCLIState } from "../../ui/use-cli-state.js";
import {
  codeSandboxSummary,
  DOCKER_GROUP_NOTE,
  savedProviderSummary,
  upHeadline,
} from "./flow.js";

const BUILD_WAIT_HINT =
  "This can take 5-30 min on 4 GB RAM — please do not cancel.";

const UpFinishedStep: React.FC<{
  webUrl: string;
  reachableUrls: string[];
  apiUrl: string;
  noStart: boolean;
  stillStarting: boolean;
  savedProvider?: string;
  codeSandbox: boolean;
  setupComplete: boolean;
  joinedDockerGroup: boolean;
}> = ({
  webUrl,
  reachableUrls,
  apiUrl,
  noStart,
  stillStarting,
  savedProvider,
  codeSandbox,
  setupComplete,
  joinedDockerGroup,
}) => {
  const success = !noStart && !stillStarting;
  return (
    <Box
      flexDirection="column"
      marginTop={2}
      borderStyle={BOX_BORDER}
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

      {!setupComplete && (
        <Box marginTop={1}>
          <Text>
            Finish setup in your browser:{" "}
            <Text color="cyan" bold underline>
              {webUrl}/setup
            </Text>
          </Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text color="gray">{codeSandboxSummary(codeSandbox)}</Text>
      </Box>

      {savedProvider && (
        <Box marginTop={1}>
          <Text color="gray">{savedProviderSummary(savedProvider)}</Text>
        </Box>
      )}

      {joinedDockerGroup && (
        <Box marginTop={1}>
          <Text color="yellow">{DOCKER_GROUP_NOTE}</Text>
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
    </Box>
  );
};

/** The install and port-conflict prompts, the only input gaia up asks for. */
const UpPromptStep: React.FC<{ state: CLIState; store: CLIStore }> = ({
  state,
  store,
}) => {
  switch (state.inputRequest?.id) {
    case "port_conflicts":
      return state.data.portConflicts ? (
        <PortConflictStep
          portResults={state.data.portConflicts}
          onAccept={() => store.submitInput("accept")}
          onAbort={() => store.submitInput("abort")}
        />
      ) : null;
    default:
      return (
        <InstallConfirmStep
          inputId={state.inputRequest?.id}
          onConfirm={() => store.submitInput("install")}
          onDecline={() => store.submitInput("decline")}
        />
      );
  }
};

/** Image build and container start progress, shown until the instance is up. */
const UpStartStep: React.FC<{ state: CLIState }> = ({ state }) => {
  const phase = state.data.dependencyPhase || "";
  const starting =
    (state.step === "Project Setup" || state.step === "Finished") &&
    !state.data.finished &&
    phase !== "";
  if (!starting) return null;
  return (
    <DependencyInstallStep
      title="Starting GAIA"
      phase={phase}
      progress={state.data.dependencyProgress || 0}
      isComplete={state.data.dependencyComplete || false}
      logs={state.data.dependencyLogs}
      hint={
        phase.toLowerCase().includes("building") ? BUILD_WAIT_HINT : undefined
      }
    />
  );
};

/** The finish summary, once gaia up has nothing left to do. */
const UpSummaryStep: React.FC<{ state: CLIState }> = ({ state }) => {
  if (state.step !== "Finished" || !state.data.finished) return null;
  const noStart = state.data.upNoStart === true;
  return (
    <UpFinishedStep
      webUrl={state.data.upWebUrl}
      reachableUrls={state.data.upReachableUrls}
      apiUrl={state.data.upApiUrl}
      noStart={noStart}
      stillStarting={!noStart && state.data.upStillStarting === true}
      savedProvider={state.data.upSavedProvider}
      codeSandbox={state.data.upCodeSandbox === true}
      setupComplete={state.data.upSetupComplete === true}
      joinedDockerGroup={state.data.upJoinedDockerGroup === true}
    />
  );
};

export const UpScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
  const state = useCLIState(store);
  const idle = !state.inputRequest;

  return (
    <Shell status={state.status} step={state.step} steps={UP_STEPS}>
      {state.step === "Prerequisites" && state.data.checks && (
        <SystemChecksStep checks={state.data.checks} />
      )}

      <UpPromptStep state={state} store={store} />

      {state.step === "Repository Setup" && idle && (
        <RepositoryProgressStep
          title="Downloading GAIA"
          progress={state.data.repoProgress}
          phase={state.data.repoPhase}
        />
      )}

      {state.step === "Environment Setup" && idle && (
        <EnvSetupSpinnerStep status={state.status} />
      )}

      <UpStartStep state={state} />

      <UpSummaryStep state={state} />

      {state.error && <ErrorStep message={state.error.message} />}
    </Shell>
  );
};
