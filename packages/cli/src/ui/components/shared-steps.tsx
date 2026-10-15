import { ProgressBar, Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import { INSTALL_CONFIRM_INPUT } from "../../lib/prerequisites.js";
import type { PortCheckResult } from "../../lib/prerequisites.types.js";
import { THEME_COLOR } from "../constants.js";

export const SystemChecksStep: React.FC<{
  checks: { git: string; docker?: string; mise?: string };
}> = ({ checks }) => (
  <Box
    flexDirection="column"
    borderStyle="round"
    paddingX={1}
    borderColor={THEME_COLOR}
  >
    <Text bold>System Checks</Text>
    <Box flexDirection="column" marginTop={1}>
      <CheckItem
        label="Git"
        status={checks.git as "pending" | "success" | "error" | "missing"}
      />
      {checks.docker && (
        <CheckItem
          label="Docker"
          status={checks.docker as "pending" | "success" | "error" | "missing"}
        />
      )}
      {checks.mise && (
        <CheckItem
          label="Mise"
          status={checks.mise as "pending" | "success" | "error" | "missing"}
        />
      )}
    </Box>
  </Box>
);

export const EnvSetupSpinnerStep: React.FC<{ status?: string }> = ({
  status,
}) => (
  <Box
    flexDirection="column"
    marginTop={1}
    paddingX={1}
    borderStyle="round"
    borderColor={THEME_COLOR}
  >
    <Text bold>Environment Setup</Text>
    <Box marginTop={1}>
      <Spinner label={status || "Configuring environment..."} />
    </Box>
  </Box>
);

export const RepositoryProgressStep: React.FC<{
  title: string;
  progress?: number;
  phase?: string;
}> = ({ title, progress, phase }) => (
  <Box
    flexDirection="column"
    borderStyle="round"
    padding={1}
    borderColor={THEME_COLOR}
  >
    <Text bold>{title}</Text>
    <Box marginTop={1} flexDirection="column">
      <ProgressBar value={progress || 0} />
      {phase && (
        <Box marginTop={1}>
          <Text color="gray">{phase}</Text>
        </Box>
      )}
    </Box>
  </Box>
);

export const ErrorStep: React.FC<{ message: string }> = ({ message }) => (
  <Box
    flexDirection="column"
    borderStyle="single"
    borderColor="red"
    padding={1}
    marginTop={2}
  >
    <Text color="red">Error: {message}</Text>
    <Box marginTop={1}>
      <Text dimColor>
        <Text bold>Enter</Text> to exit
      </Text>
    </Box>
  </Box>
);

const CheckItem: React.FC<{
  label: string;
  status: "pending" | "success" | "error" | "missing";
}> = ({ label, status }) => (
  <Box>
    <Box marginRight={1}>
      {status === "pending" ? (
        <Spinner type="dots" />
      ) : status === "success" ? (
        <Text color="green">✔</Text>
      ) : status === "error" ? (
        <Text color="red">✖</Text>
      ) : (
        <Text color="yellow">⚠</Text>
      )}
    </Box>
    <Text>{label}</Text>
  </Box>
);

export const PortConflictStep: React.FC<{
  portResults: PortCheckResult[];
  onAccept: () => void;
  onAbort: () => void;
}> = ({ portResults, onAccept, onAbort }) => {
  useInput((_input, key) => {
    if (key.return) onAccept();
    else if (key.escape) onAbort();
  });

  const conflicts = portResults.filter((r) => !r.available);

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor="yellow"
    >
      <Box marginBottom={1}>
        <Text bold color="yellow">
          Port Conflicts Detected
        </Text>
      </Box>

      {portResults.map((result) => (
        <Box key={result.port}>
          <Text
            color={
              result.available ? "green" : result.alternative ? "yellow" : "red"
            }
          >
            {result.available ? "✔" : result.alternative ? "⚠" : "✖"}{" "}
          </Text>
          <Text>
            {result.service} (:{result.port})
          </Text>
          {!result.available && (
            <Text color={result.alternative ? "gray" : "red"}>
              {" "}
              - in use{result.usedBy ? ` by ${result.usedBy}` : ""}
              {result.alternative
                ? ` → will use :${result.alternative}`
                : " — NO ALTERNATIVE FOUND"}
            </Text>
          )}
        </Box>
      ))}

      {conflicts.some((c) => !c.alternative) && (
        <Box marginTop={1}>
          <Text color="red">
            Some ports have no available alternative. Free them and retry.
          </Text>
        </Box>
      )}
      {!conflicts.some((c) => !c.alternative) &&
        conflicts.some((c) => c.alternative) && (
          <Box marginTop={1}>
            <Text color="gray">
              Alternative ports will be used for conflicting services.
            </Text>
          </Box>
        )}
      <Box marginTop={1}>
        <Text dimColor>
          <Text bold>Enter</Text> continue · <Text bold>ESC</Text> abort
        </Text>
      </Box>
    </Box>
  );
};

/** The copy for each install confirmation, by its input id. */
const INSTALL_PROMPTS: Record<string, { title: string; detail: string }> = {
  [INSTALL_CONFIRM_INPUT.docker]: {
    title: "Install Docker Engine now? (recommended)",
    detail: "Runs the official Docker install script — needs sudo/apt.",
  },
  [INSTALL_CONFIRM_INPUT.git]: {
    title: "Install Git now?",
    detail: "Installs git with apt — needs sudo.",
  },
};

const InstallPrompt: React.FC<{
  title: string;
  detail: string;
  onConfirm: () => void;
  onDecline: () => void;
}> = ({ title, detail, onConfirm, onDecline }) => {
  useInput((_input, key) => {
    if (key.return) onConfirm();
    if (key.escape) onDecline();
  });

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor="yellow"
    >
      <Text bold color="yellow">
        {title}
      </Text>
      <Box marginTop={1} flexDirection="column">
        <Text>{detail}</Text>
        <Text color="gray" dimColor>
          Enter to install · Esc to cancel
        </Text>
      </Box>
    </Box>
  );
};

/**
 * Confirmation shown when a prerequisite (Docker, git) is missing on an
 * apt-based Linux host; renders nothing for any other input. Enter accepts
 * the guided install; Escape declines and the flow aborts with remediation copy.
 */
export const InstallConfirmStep: React.FC<{
  inputId: string | undefined;
  onConfirm: () => void;
  onDecline: () => void;
}> = ({ inputId, onConfirm, onDecline }) => {
  const prompt = inputId === undefined ? undefined : INSTALL_PROMPTS[inputId];
  if (!prompt) return null;
  return (
    <InstallPrompt {...prompt} onConfirm={onConfirm} onDecline={onDecline} />
  );
};
