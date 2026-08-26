/**
 * Ink screen for `gaia up`. Reuses the shared step components and renders
 * only the states the up flow drives; all prompts are pre-answered by the
 * values layer except the explicit Docker-install confirmation.
 * @module commands/up/screen
 */

import { ProgressBar, Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useState } from "react";
import { Shell } from "../../ui/components/Shell.js";
import {
  DockerInstallConfirmStep,
  EnvSetupSpinnerStep,
  ErrorStep,
  PortConflictStep,
  SystemChecksStep,
} from "../../ui/components/shared-steps.js";
import { THEME_COLOR } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";

const DependencyInstallStep: React.FC<{
  phase: string;
  progress: number;
  isComplete: boolean;
  logs?: string[];
}> = ({ phase, progress, isComplete, logs }) => {
  const window = logs?.slice(-8) ?? [];
  const isBuilding = phase.toLowerCase().includes("building");
  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor={THEME_COLOR}
    >
      <Box marginBottom={1}>
        <Text bold color={THEME_COLOR}>
          Starting GAIA
        </Text>
      </Box>
      <Box flexDirection="column" gap={1}>
        <Box>
          {!isComplete ? (
            <Spinner label={phase || "Preparing..."} />
          ) : (
            <Text color="green">✓ {phase}</Text>
          )}
        </Box>
        {!isComplete && isBuilding && (
          <Box>
            <Text color="gray" dimColor>
              This can take 5-30 min on 4 GB RAM — please do not cancel.
            </Text>
          </Box>
        )}
        {!isComplete && progress > 0 && (
          <Box width={50}>
            <ProgressBar value={progress} />
          </Box>
        )}
        {window.length > 0 &&
          window.map((line, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: append-only log lines
            <Text key={`${i}-${line}`} color="gray" wrap="truncate">
              {line}
            </Text>
          ))}
      </Box>
    </Box>
  );
};

const UpFinishedStep: React.FC<{
  webPort: number;
  apiPort: number;
  noStart: boolean;
  stillStarting: boolean;
  customProviderNote: boolean;
  webDriftDetected?: boolean;
}> = ({
  webPort,
  apiPort,
  noStart,
  stillStarting,
  customProviderNote,
  webDriftDetected,
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
        {noStart
          ? "Environment Ready"
          : stillStarting
            ? "GAIA is Still Starting"
            : "GAIA is Running!"}
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
        <Text>
          Finish setup in your browser:{" "}
          <Text color="cyan" bold underline>
            http://localhost:{webPort}/setup
          </Text>
        </Text>
      </Box>

      {customProviderNote && (
        <Box marginTop={1}>
          <Text color="gray">
            Custom LLM providers are configured in the setup wizard.
          </Text>
        </Box>
      )}

      {webDriftDetected && (
        <Box marginTop={1}>
          <Text color="yellow">
            Web source changed since last build — run 'gaia up --build' to
            rebuild
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
        <Box
          flexDirection="column"
          borderStyle="round"
          padding={1}
          borderColor={THEME_COLOR}
        >
          <Text bold>Setting Up Repository</Text>
          <Box marginTop={1} flexDirection="column">
            <ProgressBar value={state.data.repoProgress || 0} />
            {state.data.repoPhase && (
              <Box marginTop={1}>
                <Text color="gray">{state.data.repoPhase}</Text>
              </Box>
            )}
          </Box>
        </Box>
      )}

      {state.step === "Environment Setup" && !state.inputRequest && (
        <EnvSetupSpinnerStep status={state.status} />
      )}

      {(state.step === "Project Setup" || state.step === "Finished") &&
        !state.data.finished &&
        state.data.dependencyPhase && (
          <DependencyInstallStep
            phase={state.data.dependencyPhase || ""}
            progress={state.data.dependencyProgress || 0}
            isComplete={state.data.dependencyComplete || false}
            logs={state.data.dependencyLogs || []}
          />
        )}

      {state.step === "Finished" && state.data.finished && (
        <UpFinishedStep
          webPort={state.data.upWebPort || 3000}
          apiPort={state.data.upApiPort || 8000}
          noStart={state.data.upNoStart === true}
          stillStarting={
            state.data.upNoStart !== true && state.data.upStillStarting === true
          }
          customProviderNote={state.data.customProviderNote === true}
          webDriftDetected={state.data.webDriftDetected === true}
        />
      )}

      {state.error && <ErrorStep message={state.error.message} />}
    </Shell>
  );
};
