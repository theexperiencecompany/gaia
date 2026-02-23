/**
 * Init screen components for the GAIA CLI setup wizard.
 * Contains all step-specific UI components for the initialization flow.
 * @module screens/init
 */

import { ProgressBar, Select, Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import type { EnvCategory, EnvVar, SetupMode } from "../../lib/env-parser.js";

import { Shell } from "../components/Shell.js";
import {
  EnvSetupSpinnerStep,
  ErrorStep,
  PortConflictStep,
  SystemChecksStep,
} from "../components/shared-steps.js";
import { THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";

/**
 * Props for the WelcomeStep component.
 */
interface WelcomeStepProps {
  /** Callback when user confirms to proceed */
  onConfirm: () => void;
}

/**
 * Welcome step showing introduction and instructions.
 * User presses Enter to continue.
 */
const WelcomeStep: React.FC<WelcomeStepProps> = ({ onConfirm }) => {
  useInput((_input, key) => {
    if (key.return) {
      onConfirm();
    }
  });

  return (
    <Box
      flexDirection="column"
      paddingX={2}
      borderStyle="round"
      borderColor={THEME_COLOR}
    >
      <Text bold>Welcome to GAIA Setup</Text>

      <Box flexDirection="column" marginTop={1} marginBottom={1}>
        <Text>This wizard will guide you through the setup process:</Text>
        <Text> 1. Check prerequisites and choose setup mode</Text>
        <Text> 2. Clone repository</Text>
        <Text> 3. Configure environment variables</Text>
        <Text> 4. Install tools and dependencies</Text>
      </Box>
      <Text dimColor>~5-15 min depending on network speed</Text>
      <Box marginTop={1}>
        <Text color={THEME_COLOR}>
          <Text bold>Enter</Text> to start
        </Text>
      </Box>
    </Box>
  );
};

const PathInputStep: React.FC<{
  defaultValue: string;
  onSubmit: (val: string) => void;
}> = ({ defaultValue, onSubmit }) => {
  const [value, setValue] = useState(defaultValue);

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor={THEME_COLOR}
    >
      <Text>Clone repository to:</Text>
      <Text color="gray" dimColor>
        Press Enter for default, or type a custom path
      </Text>
      <Box marginTop={1}>
        <Text color={THEME_COLOR}>→ </Text>
        <TextInput value={value} onChange={setValue} onSubmit={onSubmit} />
      </Box>
    </Box>
  );
};

const ExistingRepoStep: React.FC<{
  repoPath: string;
  onAction: (action: string) => void;
}> = ({ repoPath, onAction }) => {
  const options = [
    { label: "Use existing installation", value: "use_existing" },
    { label: "Delete and re-clone", value: "delete_reclone" },
    { label: "Choose a different path", value: "different_path" },
    { label: "Exit setup", value: "exit" },
  ];

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
          Existing Installation Found
        </Text>
      </Box>
      <Text>
        Found a GAIA installation at{" "}
        <Text color="cyan" bold>
          {repoPath}
        </Text>
      </Text>
      <Box marginTop={1}>
        <Text color="gray">What would you like to do?</Text>
      </Box>
      <Box marginTop={1}>
        <Select options={options} onChange={(value) => onAction(value)} />
      </Box>
    </Box>
  );
};

const FinishedStep: React.FC<{
  setupMode?: SetupMode;
  portOverrides?: Record<number, number>;
  onConfirm: () => void;
}> = ({ setupMode, portOverrides, onConfirm }) => {
  useInput((_input, key) => {
    if (key.return) {
      onConfirm();
    }
  });

  const webPort = portOverrides?.[3000] ?? 3000;
  const apiPort = portOverrides?.[8000] ?? 8000;

  if (setupMode === "selfhost") {
    return (
      <Box
        flexDirection="column"
        marginTop={2}
        borderStyle="round"
        borderColor="green"
        padding={1}
      >
        <Text bold color="green">
          GAIA is Running!
        </Text>

        <Box marginTop={1}>
          <Text color="green">✓ All services started</Text>
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
          <Text color="gray">gaia logs · gaia stop · gaia status · gaia setup</Text>
        </Box>

        <Box marginTop={1}>
          <Text dimColor>
            <Text bold>Enter</Text> to exit
          </Text>
        </Box>
      </Box>
    );
  }

  return (
    <Box
      flexDirection="column"
      marginTop={2}
      borderStyle="round"
      borderColor={THEME_COLOR}
      padding={1}
    >
      <Text color={THEME_COLOR} bold>
        You're all set!
      </Text>

      <Box marginTop={1}>
        <Text bold>Run: </Text>
        <Text color="cyan">$ gaia dev</Text>
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
          gaia dev full · gaia logs · gaia stop · gaia status · gaia setup
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

// Dependency installation progress step
const LOG_WINDOW_HEIGHT = 8;

const LogWindow: React.FC<{ logs: string[]; height?: number }> = ({
  logs,
  height = LOG_WINDOW_HEIGHT,
}) => {
  const [scrollOffset, setScrollOffset] = useState(0);

  // Auto-scroll to bottom when new logs arrive, unless user has scrolled up
  const prevLenRef = useRef(logs.length);
  useEffect(() => {
    if (logs.length !== prevLenRef.current) {
      prevLenRef.current = logs.length;
      setScrollOffset(0);
    }
  }, [logs.length]);

  useInput((_input, key) => {
    if (key.upArrow) {
      setScrollOffset((o) =>
        Math.min(o + 1, Math.max(0, logs.length - height)),
      );
    } else if (key.downArrow) {
      setScrollOffset((o) => Math.max(0, o - 1));
    }
  });

  const totalLines = logs.length;
  const start = Math.max(0, totalLines - height - scrollOffset);
  const end = Math.max(0, totalLines - scrollOffset);
  const visible = logs.slice(start, end);
  const linesAbove = start;
  const linesBelow = scrollOffset;

  return (
    <Box flexDirection="column" marginTop={1} marginLeft={1}>
      {linesAbove > 0 && (
        <Text color="gray" dimColor>
          ↑ {linesAbove} more line{linesAbove !== 1 ? "s" : ""}
        </Text>
      )}
      <Box flexDirection="column" height={height} overflow="hidden">
        {visible.map((log, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: logs are append-only
          <Text key={`${start}-${i}`} color="gray" wrap="truncate">
            {log}
          </Text>
        ))}
      </Box>
      {linesBelow > 0 ? (
        <Text color="gray" dimColor>
          ↓ {linesBelow} more line{linesBelow !== 1 ? "s" : ""}
        </Text>
      ) : (
        <Text color="gray" dimColor>
          ↑↓ scroll
        </Text>
      )}
    </Box>
  );
};

export const DependencyInstallStep: React.FC<{
  phase: string;
  progress: number;
  isComplete: boolean;
  logs?: string[];
  title?: string;
}> = ({ phase, progress, isComplete, logs, title }) => {
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
          {title || "Installing Dependencies"}
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
        {!isComplete && progress > 0 && (
          <Box width={50}>
            <ProgressBar value={progress} />
          </Box>
        )}

        {!isComplete && logs && logs.length > 0 && <LogWindow logs={logs} />}

        {!isComplete && (
          <Box marginTop={1}>
            <Text color="gray" dimColor>
              This may take a few minutes...
            </Text>
          </Box>
        )}
      </Box>
    </Box>
  );
};

// Start services prompt step
export const StartServicesStep: React.FC<{
  setupMode: SetupMode;
  repoPath: string;
  onStart: () => void;
  onSkip: () => void;
}> = ({ setupMode, repoPath, onStart, onSkip }) => {
  useInput((_input, key) => {
    if (key.return) {
      onStart();
    } else if (key.escape) {
      onSkip();
    }
  });

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
          Ready to Start GAIA
        </Text>
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text color="gray">Dependencies installed successfully!</Text>
        <Text color="gray">Project location: {repoPath}</Text>
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text bold>What happens next:</Text>
        <Box marginLeft={2} flexDirection="column">
          {setupMode === "selfhost" ? (
            <>
              <Text>
                1. Start all Docker services (backend, worker, databases)
              </Text>
              <Text>2. Build and start the web frontend</Text>
            </>
          ) : (
            <>
              <Text>1. Start Docker database services</Text>
              <Text>2. Start API server in development mode</Text>
              <Text>3. Start web frontend in development mode</Text>
            </>
          )}
        </Box>
      </Box>

      <Box flexDirection="column" marginTop={1} marginLeft={2}>
        <Text dimColor>Command that will run:</Text>
        {setupMode === "selfhost" ? (
          <Box flexDirection="column">
            <Text color="cyan">$ docker compose --profile all up -d</Text>
            <Text color="cyan">$ nx build web</Text>
            <Text color="cyan">$ nx start web</Text>
          </Box>
        ) : (
          <Box flexDirection="column">
            <Text color="cyan">$ gaia dev</Text>
            <Text color="cyan">$ gaia dev full</Text>
          </Box>
        )}
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text>
          <Text dimColor>
            <Text bold>Enter</Text> start · <Text bold>ESC</Text> skip
          </Text>
        </Text>
      </Box>
    </Box>
  );
};

// Services running success step
export const ServicesRunningStep: React.FC<{
  setupMode: SetupMode;
  portOverrides?: Record<number, number>;
  onConfirm: () => void;
}> = ({ portOverrides, onConfirm }) => {
  useInput((_input, key) => {
    if (key.return) {
      onConfirm();
    }
  });

  const webPort = portOverrides?.[3000] ?? 3000;
  const apiPort = portOverrides?.[8000] ?? 8000;

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor="green"
    >
      <Text bold color="green">
        GAIA is Running!
      </Text>

      <Box marginTop={1} flexDirection="column">
        <Text color="green">✓ All services started</Text>
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
        <Text color="gray">gaia logs · gaia stop · gaia status · gaia setup</Text>
      </Box>

      <Box marginTop={1}>
        <Text dimColor>
          <Text bold>Enter</Text> to exit
        </Text>
      </Box>
    </Box>
  );
};

// Manual commands display (shown when user skips auto-start)
export const ManualCommandsStep: React.FC<{
  setupMode: SetupMode;
  onConfirm: () => void;
}> = ({ onConfirm }) => {
  useInput((_input, key) => {
    if (key.return) {
      onConfirm();
    }
  });

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor={THEME_COLOR}
    >
      <Text bold color={THEME_COLOR}>
        Setup Complete!
      </Text>

      <Box marginTop={1}>
        <Text>Run: </Text>
        <Text color="cyan" bold>
          $ gaia dev
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color="gray">
          gaia dev full · gaia logs · gaia stop · gaia status · gaia setup
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

export const SetupModeSelectionStep: React.FC<{
  onSelect: (mode: SetupMode) => void;
}> = ({ onSelect }) => {
  const options = [
    {
      label: "Self-Host — run everything in Docker",
      value: "selfhost",
    },
    {
      label: "Developer — local dev with hot reload",
      value: "developer",
    },
  ];

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor={THEME_COLOR}
    >
      <Text bold>Setup Mode</Text>
      <Box marginTop={1}>
        <Text color="gray">How do you want to run GAIA?</Text>
      </Box>
      <Box marginTop={1}>
        <Select
          options={options}
          onChange={(value) => onSelect(value as SetupMode)}
        />
      </Box>
    </Box>
  );
};

export const EnvMethodSelectionStep: React.FC<{
  onSelect: (method: string) => void;
}> = ({ onSelect }) => {
  const options = [
    {
      label: "Manual Setup (Recommended)",
      value: "manual",
    },
    {
      label: "Infisical (Advanced)",
      value: "infisical",
    },
  ];

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor={THEME_COLOR}
    >
      <Text bold>Environment Variables Setup</Text>
      <Box marginTop={1}>
        <Text color="gray">
          Choose how you want to configure environment variables:
        </Text>
      </Box>
      <Box marginTop={1}>
        <Select options={options} onChange={(value) => onSelect(value)} />
      </Box>
      <Box marginTop={1} flexDirection="column">
        <Text color="gray" dimColor>
          Manual Setup: Configure variables interactively (recommended for most
          users)
        </Text>
        <Text color="gray" dimColor>
          Infisical: All secrets managed in Infisical dashboard (requires
          pre-configuration)
        </Text>
      </Box>
    </Box>
  );
};

// Infisical setup component
export const InfisicalSetupStep: React.FC<{
  onSubmit: (values: {
    INFISICAL_TOKEN: string;
    INFISICAL_PROJECT_ID: string;
    INFISICAL_MACHINE_IDENTITY_CLIENT_ID: string;
    INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET: string;
  }) => void;
}> = ({ onSubmit }) => {
  const [values, setValues] = useState({
    INFISICAL_TOKEN: "",
    INFISICAL_PROJECT_ID: "",
    INFISICAL_MACHINE_IDENTITY_CLIENT_ID: "",
    INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET: "",
  });
  const [activeIndex, setActiveIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const fields = [
    {
      key: "INFISICAL_TOKEN" as const,
      description: "Service token from project settings (st.xxx...)",
    },
    {
      key: "INFISICAL_PROJECT_ID" as const,
      description: "Found in your Infisical project settings",
    },
    {
      key: "INFISICAL_MACHINE_IDENTITY_CLIENT_ID" as const,
      description: "From Access Control → Machine Identities",
    },
    {
      key: "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET" as const,
      description: "Generated when creating the machine identity",
    },
  ];

  useInput((_input, key) => {
    if (key.tab || key.downArrow) {
      setActiveIndex((prev) => (prev < fields.length - 1 ? prev + 1 : prev));
    } else if (key.upArrow) {
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : prev));
    } else if (key.return) {
      // If not on the last field, go to next field
      if (activeIndex < fields.length - 1) {
        setActiveIndex((prev) => prev + 1);
        return;
      }
      // On last field, validate and submit
      const missing = fields.filter((f) => !values[f.key].trim());
      if (missing.length > 0) {
        setError(`Required: ${missing.map((f) => f.key).join(", ")}`);
        // Go to first missing field
        const firstMissingIdx = fields.findIndex((f) => !values[f.key].trim());
        if (firstMissingIdx >= 0) setActiveIndex(firstMissingIdx);
        return;
      }
      onSubmit(values);
    }
  });

  const _currentField = fields[activeIndex];

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
          Infisical Configuration
        </Text>
      </Box>

      <Box marginBottom={1}>
        <Text color="gray">
          All secrets managed in your Infisical project. Only credentials stored
          locally.
        </Text>
      </Box>

      <Box marginBottom={1} flexDirection="column">
        <Text color="gray">Configure your Infisical credentials.</Text>
        <Text color="gray" dimColor>
          Visit{" "}
          <Text color="cyan" underline>
            app.infisical.com
          </Text>{" "}
          to get these values.
        </Text>
      </Box>

      {fields.map((field, idx) => {
        const isSensitive =
          field.key.includes("SECRET") || field.key.includes("TOKEN");
        return (
          <Box key={field.key} flexDirection="column" marginBottom={1}>
            <Box>
              <Text color={idx === activeIndex ? THEME_COLOR : "white"}>
                {idx === activeIndex ? "▸ " : "  "}
                {field.key}:
              </Text>
            </Box>
            <Box marginLeft={2}>
              <Text color="gray" dimColor>
                {field.description}
              </Text>
            </Box>
            {idx === activeIndex ? (
              <Box marginLeft={2}>
                <TextInput
                  value={values[field.key]}
                  onChange={(v) => {
                    setValues((prev) => ({ ...prev, [field.key]: v }));
                    setError(null);
                  }}
                  placeholder="Enter value..."
                  mask={isSensitive ? "*" : undefined}
                />
              </Box>
            ) : (
              <Box marginLeft={2}>
                <Text color={values[field.key] ? "green" : "gray"}>
                  {values[field.key]
                    ? isSensitive
                      ? `✓ ${"*".repeat(8)}`
                      : `✓ ${values[field.key]}`
                    : "(not set)"}
                </Text>
              </Box>
            )}
          </Box>
        );
      })}

      {error && (
        <Box marginTop={1}>
          <Text color="red">{error}</Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor>
          <Text bold>Enter</Text> confirm · <Text bold>↑↓</Text> navigate
        </Text>
      </Box>
    </Box>
  );
};

// Component for configuring multiple env vars in a group at once
export const EnvGroupConfigStep: React.FC<{
  category: EnvCategory;
  currentIndex: number;
  totalGroups: number;
  onSubmit: (values: Record<string, string>) => void;
}> = ({ category, currentIndex, totalGroups, onSubmit }) => {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const v of category.variables) {
      initial[v.name] = v.defaultValue || "";
    }
    return initial;
  });
  const [activeIndex, setActiveIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Reset when category changes
  useEffect(() => {
    const initial: Record<string, string> = {};
    for (const v of category.variables) {
      initial[v.name] = v.defaultValue || "";
    }
    setValues(initial);
    setActiveIndex(0);
    setError(null);
  }, [category.name]);

  useInput((_input, key) => {
    if (key.tab || key.downArrow) {
      // Move to next field
      setActiveIndex((prev) =>
        prev < category.variables.length - 1 ? prev + 1 : prev,
      );
    } else if (key.upArrow) {
      // Move to previous field
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : prev));
    } else if (key.escape) {
      // Skip entire group if no required fields are empty
      const missingRequired = category.variables.filter(
        (v) => v.required && !values[v.name]?.trim(),
      );
      if (missingRequired.length > 0) {
        setError(
          `Required fields cannot be skipped: ${missingRequired.map((v) => v.name).join(", ")}`,
        );
        return;
      }
      onSubmit(values);
    }
  });

  const handleFieldSubmit = () => {
    // Move to next field or submit group
    if (activeIndex < category.variables.length - 1) {
      setActiveIndex(activeIndex + 1);
    } else {
      // Validate all required fields
      const missingRequired = category.variables.filter(
        (v) => v.required && !values[v.name]?.trim(),
      );
      if (missingRequired.length > 0) {
        setError(
          `Required fields are missing: ${missingRequired.map((v) => v.name).join(", ")}`,
        );
        return;
      }
      setError(null);
      onSubmit(values);
    }
  };

  const hasAnyRequired = category.variables.some((v) => v.required);

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor={error ? "red" : THEME_COLOR}
    >
      <Box justifyContent="space-between">
        <Text bold>Configure {category.name}</Text>
        <Text color="gray">
          Group {currentIndex + 1} / {totalGroups}
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color="gray">{category.description}</Text>
      </Box>

      {/* All variables in the group */}
      <Box marginTop={1} flexDirection="column">
        {category.variables.map((envVar, idx) => {
          const isActive = idx === activeIndex;
          const hasDefault = !!envVar.defaultValue;

          return (
            <Box key={envVar.name} flexDirection="column" marginBottom={1}>
              <Box>
                <Text color={isActive ? THEME_COLOR : "gray"} bold={isActive}>
                  {isActive ? "➜ " : "  "}
                  {envVar.name}
                </Text>
                {envVar.required && (
                  <Text color="red" bold>
                    {" "}
                    *
                  </Text>
                )}
                {hasDefault && !isActive && (
                  <Text color="gray" dimColor>
                    {" "}
                    (default: {envVar.defaultValue})
                  </Text>
                )}
              </Box>

              {isActive && (
                <Box marginLeft={2}>
                  <TextInput
                    value={values[envVar.name] || ""}
                    onChange={(newValue) => {
                      setValues((prev) => ({
                        ...prev,
                        [envVar.name]: newValue,
                      }));
                      if (error) setError(null);
                    }}
                    onSubmit={handleFieldSubmit}
                    placeholder={
                      hasDefault
                        ? `Default: ${envVar.defaultValue}`
                        : envVar.required
                          ? "Enter a value (required)"
                          : "Press Enter to skip"
                    }
                  />
                </Box>
              )}
            </Box>
          );
        })}
      </Box>

      {/* Error Message */}
      {error && (
        <Box marginTop={1}>
          <Text color="red" bold>
            ⚠ {error}
          </Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor>
          <Text bold>Enter</Text> next · <Text bold>↑↓</Text> navigate
          {!hasAnyRequired && (
            <Text>
              {" "}
              · <Text bold>ESC</Text> skip
            </Text>
          )}
        </Text>
      </Box>
    </Box>
  );
};

/**
 * Props for the AlternativeGroupSelectionStep component.
 */
interface AlternativeGroupSelectionProps {
  /** Array of alternative categories (e.g., OpenAI and Google AI) */
  alternatives: EnvCategory[];
  /** Callback when user selects and configures alternatives */
  onSubmit: (selectedGroups: string[], values: Record<string, string>) => void;
}

/**
 * Represents a navigable item in the alternatives list.
 * Can be provider toggle, field input, or submit button.
 */
type NavItem =
  | { type: "provider"; categoryIndex: number }
  | { type: "field"; categoryIndex: number; fieldIndex: number }
  | { type: "submit" };

/**
 * Step for selecting and configuring one of multiple alternative service providers.
 * Shows all alternatives with checkboxes - user enables which ones to configure
 * and fills in values inline. At least one must be configured to proceed.
 */
export const AlternativeGroupSelectionStep: React.FC<
  AlternativeGroupSelectionProps
> = ({ alternatives, onSubmit }) => {
  // Track which providers are enabled (checkbox state)
  const [enabledProviders, setEnabledProviders] = useState<Set<number>>(
    new Set(),
  );
  // Track values for all providers
  const [allValues, setAllValues] = useState<Record<string, string>>({});
  // Current navigation position
  const [navIndex, setNavIndex] = useState(0);
  // Error message
  const [error, setError] = useState<string | null>(null);

  // Initialize values for all providers
  useEffect(() => {
    const initial: Record<string, string> = {};
    for (const category of alternatives) {
      for (const v of category.variables) {
        initial[v.name] = v.defaultValue || "";
      }
    }
    setAllValues(initial);
  }, [alternatives]);

  // Build navigation items list: providers + their fields (when enabled) + submit
  const navItems: NavItem[] = [];
  for (let catIdx = 0; catIdx < alternatives.length; catIdx++) {
    navItems.push({ type: "provider", categoryIndex: catIdx });
    // If provider is enabled, add its fields to navigation
    if (enabledProviders.has(catIdx)) {
      const category = alternatives[catIdx];
      if (category) {
        for (
          let fieldIdx = 0;
          fieldIdx < category.variables.length;
          fieldIdx++
        ) {
          navItems.push({
            type: "field",
            categoryIndex: catIdx,
            fieldIndex: fieldIdx,
          });
        }
      }
    }
  }
  // Add submit button as last navigable item
  navItems.push({ type: "submit" });

  const currentItem = navItems[navIndex];

  // Check if current item is a field input (vs provider toggle or submit)
  const isOnField = currentItem?.type === "field";
  const isOnSubmit = currentItem?.type === "submit";

  useInput((input, key) => {
    // Clamp navIndex if navItems changed (e.g., when toggling a provider)
    const clampedIndex = Math.min(navIndex, navItems.length - 1);
    if (clampedIndex !== navIndex) {
      setNavIndex(clampedIndex);
      return;
    }

    if (isOnField) {
      // When on a field, only handle navigation keys (not typing)
      if (key.upArrow) {
        setNavIndex((prev) => Math.max(0, prev - 1));
      } else if (key.downArrow || key.tab) {
        setNavIndex((prev) => Math.min(navItems.length - 1, prev + 1));
      }
      // Don't handle return here - TextInput handles it
    } else if (isOnSubmit) {
      // On submit button
      if (key.upArrow) {
        setNavIndex((prev) => Math.max(0, prev - 1));
      } else if (key.return || input === " ") {
        handleSubmit();
      }
    } else {
      // On provider toggle
      if (key.upArrow) {
        setNavIndex((prev) => Math.max(0, prev - 1));
      } else if (key.downArrow || key.tab) {
        setNavIndex((prev) => Math.min(navItems.length - 1, prev + 1));
      } else if (key.return || input === " ") {
        // Toggle provider enabled state
        if (currentItem?.type === "provider") {
          const catIdx = currentItem.categoryIndex;
          setEnabledProviders((prev) => {
            const next = new Set(prev);
            if (next.has(catIdx)) {
              next.delete(catIdx);
            } else {
              next.add(catIdx);
            }
            return next;
          });
          if (error) setError(null);
        }
      }
    }
  });

  const handleFieldSubmit = () => {
    if (error) setError(null);
    // Move to next item (submit button handles actual submission)
    setNavIndex((prev) => Math.min(navItems.length - 1, prev + 1));
  };

  const handleSubmit = () => {
    // Validate: at least one provider must be enabled with a value
    const configuredGroups: string[] = [];
    const configuredValues: Record<string, string> = {};

    for (const catIdx of enabledProviders) {
      const category = alternatives[catIdx];
      if (!category) continue;

      const hasValue = category.variables.some((v) =>
        allValues[v.name]?.trim(),
      );
      if (hasValue) {
        configuredGroups.push(category.name);
        // Collect values from this provider
        for (const v of category.variables) {
          const val = allValues[v.name];
          if (val) {
            configuredValues[v.name] = val;
          }
        }
      }
    }

    if (configuredGroups.length === 0) {
      if (enabledProviders.size === 0) {
        setError("Enable at least one provider (press Space or Enter)");
      } else {
        setError("Enter a value for at least one field");
      }
      return;
    }

    onSubmit(configuredGroups, configuredValues);
  };

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor={error ? "red" : THEME_COLOR}
    >
      <Box justifyContent="space-between">
        <Text bold>Configure AI Provider</Text>
        <Text color="yellow">* At least one required</Text>
      </Box>

      <Box marginTop={1}>
        <Text color="gray">
          Enable and configure at least one AI provider below:
        </Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        {alternatives.map((category, catIdx) => {
          const isEnabled = enabledProviders.has(catIdx);
          const providerNavIdx = navItems.findIndex(
            (item) => item.type === "provider" && item.categoryIndex === catIdx,
          );
          const isProviderFocused = navIndex === providerNavIdx;

          return (
            <Box key={category.name} flexDirection="column" marginBottom={1}>
              {/* Provider toggle row */}
              <Box>
                <Text
                  color={isProviderFocused ? THEME_COLOR : undefined}
                  bold={isProviderFocused}
                >
                  {isProviderFocused ? "➜ " : "  "}
                </Text>
                <Text color={isEnabled ? "green" : "gray"}>
                  {isEnabled ? "[✔]" : "[ ]"}
                </Text>
                <Text color={isEnabled ? THEME_COLOR : "gray"} bold={isEnabled}>
                  {" "}
                  {category.name}
                </Text>
                {category.description && (
                  <Text color="gray" dimColor>
                    {" "}
                    - {category.description}
                  </Text>
                )}
              </Box>

              {/* Show docs link when focused */}
              {isProviderFocused && category.docsUrl && (
                <Box marginLeft={6}>
                  <Text color="yellow">📖 </Text>
                  <Text color="blue" underline>
                    {category.docsUrl}
                  </Text>
                </Box>
              )}

              {/* Show fields when enabled */}
              {isEnabled && (
                <Box marginLeft={4} flexDirection="column" marginTop={1}>
                  {category.variables.map((envVar, fieldIdx) => {
                    const fieldNavIdx = navItems.findIndex(
                      (item) =>
                        item.type === "field" &&
                        item.categoryIndex === catIdx &&
                        item.fieldIndex === fieldIdx,
                    );
                    const isFieldFocused = navIndex === fieldNavIdx;
                    const hasDefault = !!envVar.defaultValue;
                    const currentValue = allValues[envVar.name] || "";

                    return (
                      <Box
                        key={envVar.name}
                        flexDirection="column"
                        marginBottom={1}
                      >
                        <Box>
                          <Text
                            color={isFieldFocused ? THEME_COLOR : "gray"}
                            bold={isFieldFocused}
                          >
                            {isFieldFocused ? "  ➜ " : "    "}
                            {envVar.name}
                          </Text>
                          {!isFieldFocused && currentValue && (
                            <Text color="green"> ✓</Text>
                          )}
                          {!isFieldFocused && !currentValue && hasDefault && (
                            <Text color="gray" dimColor>
                              {" "}
                              (default: {envVar.defaultValue})
                            </Text>
                          )}
                        </Box>

                        {isFieldFocused && (
                          <Box marginLeft={4}>
                            <TextInput
                              value={currentValue}
                              onChange={(newValue) => {
                                setAllValues((prev) => ({
                                  ...prev,
                                  [envVar.name]: newValue,
                                }));
                                if (error) setError(null);
                              }}
                              onSubmit={handleFieldSubmit}
                              placeholder={
                                hasDefault
                                  ? `Default: ${envVar.defaultValue}`
                                  : "Enter value..."
                              }
                            />
                          </Box>
                        )}
                      </Box>
                    );
                  })}
                </Box>
              )}
            </Box>
          );
        })}
      </Box>

      {error && (
        <Box marginTop={1}>
          <Text color="red" bold>
            ⚠ {error}
          </Text>
        </Box>
      )}

      {/* Submit button */}
      <Box marginTop={1}>
        <Text color={isOnSubmit ? THEME_COLOR : undefined} bold={isOnSubmit}>
          {isOnSubmit ? "➜ " : "  "}
        </Text>
        <Box
          borderStyle="round"
          borderColor={isOnSubmit ? THEME_COLOR : "gray"}
          paddingX={2}
        >
          <Text color={isOnSubmit ? THEME_COLOR : "gray"} bold={isOnSubmit}>
            Continue →
          </Text>
        </Box>
      </Box>

      <Box marginTop={1}>
        <Text color="gray" dimColor>
          ↑/↓ navigate • Space/Enter toggle/select • Tab skip field
        </Text>
      </Box>
    </Box>
  );
};

export const EnvConfigStep: React.FC<{
  categories: EnvCategory[];
  currentVar: EnvVar;
  currentIndex: number;
  totalCount: number;
  onSubmit: (value: string) => void;
  onSkip: () => void;
}> = ({ currentVar, currentIndex, totalCount, onSubmit, onSkip }) => {
  const [value, setValue] = useState(currentVar.defaultValue || "");
  const [error, setError] = useState<string | null>(null);

  // Reset value when currentVar changes
  useEffect(() => {
    setValue(currentVar.defaultValue || "");
    setError(null);
  }, [currentVar.name]);

  useInput((_input, key) => {
    if (key.escape) {
      if (currentVar.required && !value.trim()) {
        setError("This field is required and cannot be skipped");
        return;
      }
      onSkip();
    }
  });

  const handleSubmit = (submittedValue: string) => {
    if (currentVar.required && !submittedValue.trim()) {
      setError("This field is required");
      return;
    }
    setError(null);
    onSubmit(submittedValue);
  };

  const hasDefault = !!currentVar.defaultValue;

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      paddingX={1}
      borderStyle="round"
      borderColor={error ? "red" : THEME_COLOR}
    >
      <Box justifyContent="space-between">
        <Box>
          <Text color={THEME_COLOR} bold>
            {currentVar.name}
          </Text>
          {currentVar.required ? (
            <Text color="red"> *</Text>
          ) : (
            <Text color="gray" dimColor>
              {" "}
              optional
            </Text>
          )}
        </Box>
        <Text color="gray">
          {currentIndex + 1}/{totalCount}
        </Text>
      </Box>

      <Box marginLeft={1}>
        <Text color="gray">{currentVar.description}</Text>
      </Box>

      <Box marginTop={1}>
        <Text color={THEME_COLOR}>→ </Text>
        <TextInput
          value={value}
          onChange={(newValue) => {
            setValue(newValue);
            if (error) setError(null);
          }}
          onSubmit={handleSubmit}
          placeholder={
            hasDefault
              ? `Default: ${currentVar.defaultValue}`
              : currentVar.required
                ? "required"
                : "skip with Enter"
          }
        />
      </Box>

      {error && (
        <Box marginTop={1}>
          <Text color="red">{error}</Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor>
          <Text bold>Enter</Text> confirm
          {!currentVar.required && (
            <Text>
              {" "}
              · <Text bold>ESC</Text> skip
            </Text>
          )}
        </Text>
      </Box>
    </Box>
  );
};

export const InitScreen: React.FC<{ store: CLIStore }> = ({ store }) => {
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
      {state.step === "Welcome" && state.inputRequest?.id === "welcome" && (
        <WelcomeStep onConfirm={() => store.submitInput(true)} />
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

      {state.inputRequest?.id === "repo_path" && (
        <PathInputStep
          defaultValue={state.inputRequest.meta.default}
          onSubmit={(value) => store.submitInput(value)}
        />
      )}

      {state.inputRequest?.id === "existing_repo" &&
        state.data.existingRepoPath && (
          <ExistingRepoStep
            repoPath={state.data.existingRepoPath}
            onAction={(action) => store.submitInput(action)}
          />
        )}

      {state.step === "Repository Setup" && !state.inputRequest && (
        <Box
          flexDirection="column"
          borderStyle="round"
          padding={1}
          borderColor={THEME_COLOR}
        >
          <Text bold>Cloning Repository</Text>
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

      {state.step === "Finished" && (
        <FinishedStep
          setupMode={state.data.setupMode}
          portOverrides={state.data.portOverrides}
          onConfirm={() => store.submitInput("exit")}
        />
      )}

      {(state.step === "Install Tools" || state.step === "Project Setup") && (
        <DependencyInstallStep
          title={
            state.step === "Install Tools"
              ? "Installing Tools"
              : "Project Setup"
          }
          phase={state.data.dependencyPhase || ""}
          progress={state.data.dependencyProgress || 0}
          isComplete={
            state.step === "Install Tools"
              ? state.data.toolComplete || false
              : state.data.dependencyComplete || false
          }
          logs={state.data.dependencyLogs || []}
        />
      )}

      {state.error && <ErrorStep message={state.error.message} />}
    </Shell>
  );
};
