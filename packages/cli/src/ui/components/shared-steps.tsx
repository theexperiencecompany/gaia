import { Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import type { PortCheckResult } from "../../lib/prerequisites.js";
import { THEME_COLOR } from "../constants.js";

export const SystemChecksStep: React.FC<{
  checks: { git: string; docker: string; mise: string };
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
      <CheckItem
        label="Docker"
        status={checks.docker as "pending" | "success" | "error" | "missing"}
      />
      <CheckItem
        label="Mise"
        status={checks.mise as "pending" | "success" | "error" | "missing"}
      />
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

export const CheckItem: React.FC<{
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
