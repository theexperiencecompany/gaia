import { Alert, ConfirmInput, Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import type React from "react";
import {
  INSTALL_CONFIRM_INPUT,
  type InstallablePrerequisite,
  joinNames,
} from "../../lib/prerequisite-install.js";
import type { PortCheckResult } from "../../lib/prerequisites.types.js";
import { BOX_BORDER, MARK, type MarkKind, THEME_COLOR } from "../constants.js";
import { Mark } from "./Mark.js";
import { PercentBar } from "./PercentBar.js";
import { useCardWidth } from "./use-card-width.js";

export const SystemChecksStep: React.FC<{
  checks: { git: string; docker?: string; mise?: string };
}> = ({ checks }) => (
  <Box
    flexDirection="column"
    borderStyle={BOX_BORDER}
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
    borderStyle={BOX_BORDER}
    borderColor={THEME_COLOR}
  >
    <Text bold>Environment Setup</Text>
    <Box marginTop={1}>
      <Spinner label={status || "Configuring environment…"} />
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
    borderStyle={BOX_BORDER}
    padding={1}
    borderColor={THEME_COLOR}
  >
    <Text bold>{title}</Text>
    <Box marginTop={1} flexDirection="column">
      <PercentBar percent={progress || 0} />
      {phase && <Text color="gray">{phase}</Text>}
    </Box>
  </Box>
);

/** A failure: its first line is the cause, the rest the next step and where the log is. */
export const ErrorStep: React.FC<{ message: string }> = ({ message }) => {
  const [cause = "", ...rest] = message.split("\n");
  const width = useCardWidth();
  if (rest.length === 0) {
    // A title over an empty message would leave a blank line in the box.
    return (
      <Box marginTop={1} width={width}>
        <Alert variant="error">{cause}</Alert>
      </Box>
    );
  }
  return (
    <Box marginTop={1} width={width}>
      <Alert variant="error" title={cause}>
        {rest.map((line, i) => (
          <Text
            key={line}
            color={line.startsWith("Full log:") ? "gray" : undefined}
          >
            {i > 0 ? "\n" : ""}
            {line}
          </Text>
        ))}
      </Alert>
    </Box>
  );
};

const CHECK_MARK: Record<"success" | "error" | "missing", MarkKind> = {
  success: "ok",
  error: "fail",
  missing: "warn",
};

const CheckItem: React.FC<{
  label: string;
  status: "pending" | "success" | "error" | "missing";
}> = ({ label, status }) => (
  <Box>
    {status === "pending" ? (
      <Box marginRight={1}>
        <Spinner type="dots" />
      </Box>
    ) : (
      <Mark kind={CHECK_MARK[status]} />
    )}
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
      borderStyle={BOX_BORDER}
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
            {result.available
              ? MARK.ok
              : result.alternative
                ? MARK.warn
                : MARK.fail}{" "}
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
          <Text bold>Enter</Text> continue · <Text bold>Esc</Text> cancel
        </Text>
      </Box>
    </Box>
  );
};

const InstallPrompt: React.FC<{
  missing: readonly InstallablePrerequisite[];
  onConfirm: () => void;
  onDecline: () => void;
}> = ({ missing, onConfirm, onDecline }) => {
  const verb = missing.length > 1 ? "aren't" : "isn't";
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text>
        GAIA needs <Text bold>{joinNames(missing)}</Text>, which {verb}{" "}
        installed yet.
      </Text>
      <Box>
        <Text>
          Install {missing.length > 1 ? "them" : "it"} now?{" "}
          <Text dimColor>(uses sudo, a few minutes)</Text>{" "}
        </Text>
        <ConfirmInput onConfirm={onConfirm} onCancel={onDecline} />
      </Box>
    </Box>
  );
};

/**
 * The one install confirmation for every missing prerequisite on an apt-based
 * Linux host; renders nothing for any other input. Enter installs them all;
 * Escape declines and the flow stops with the manual-install links.
 */
export const InstallConfirmStep: React.FC<{
  inputId: string | undefined;
  missing: readonly InstallablePrerequisite[] | undefined;
  onConfirm: () => void;
  onDecline: () => void;
}> = ({ inputId, missing, onConfirm, onDecline }) => {
  if (inputId !== INSTALL_CONFIRM_INPUT || !missing?.length) return null;
  return (
    <InstallPrompt
      missing={missing}
      onConfirm={onConfirm}
      onDecline={onDecline}
    />
  );
};
