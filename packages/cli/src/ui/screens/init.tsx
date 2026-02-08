/**
 * Init screen components for the GAIA CLI setup wizard.
 * Contains all step-specific UI components for the initialization flow.
 * @module screens/init
 */

import { ProgressBar, Select, Spinner } from "@inkjs/ui";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import type React from "react";
import { useEffect, useState } from "react";
import type { EnvCategory, EnvVar, SetupMode } from "../../lib/env-parser.js";
import type { PortCheckResult } from "../../lib/prerequisites.js";
import { Shell } from "../components/Shell.js";
import { THEME_COLOR } from "../constants.js";
import type { CLIStore } from "../store.js";

/**
 * Props for the CheckItem component.
 */
interface CheckItemProps {
  /** Label text for the check item */
  label: string;
  /** Current status of the check */
  status: "pending" | "success" | "error" | "missing";
}

/**
 * Displays a single prerequisite check item with status indicator.
 * Shows spinner for pending, checkmark for success, X for error, warning for missing.
 */
const CheckItem: React.FC<CheckItemProps> = ({ label, status }) => (
  <Box>
    <Box marginRight={1}>
      {status === "pending" ? (
        <Spinner type="dots" />
      ) : status === "success" ? (
        <Text color={THEME_COLOR}>✔</Text>
      ) : status === "error" ? (
        <Text color="red">✖</Text>
      ) : (
        <Text color="yellow">⚠</Text>
      )}
    </Box>
    <Text>{label}</Text>
  </Box>
);

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
      <Text bold>Welcome to the Interactive GAIA Setup</Text>

      <Box flexDirection="column" marginTop={1} marginBottom={1}>
        <Text>This wizard will guide you through the setup process:</Text>
        <Text> 1. Check Prerequisites (Git, Docker, Mise)</Text>
        <Text> 2. Clone the Repository</Text>
        <Text> 3. Configure Environment Variables</Text>
      </Box>
      <Text color={THEME_COLOR}>Press Enter to start...</Text>
    </Box>
  );
};

const PortConflictStep: React.FC<{
  portResults: PortCheckResult[];
  onAccept: () => void;
  onAbort: () => void;
}> = ({ portResults, onAccept, onAbort }) => {
  useInput((_input, key) => {
    if (key.return) {
      onAccept();
    } else if (key.escape) {
      onAbort();
    }
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
          <Text color={result.available ? "green" : "red"}>
            {result.available ? "\u2714" : "\u2716"}{" "}
          </Text>
          <Text>
            {result.service} (:{result.port})
          </Text>
          {!result.available && (
            <Text color="gray">
              {" "}
              - in use{result.usedBy ? ` by ${result.usedBy}` : ""}
              {result.alternative
                ? ` (alt: :${result.alternative})`
                : ""}
            </Text>
          )}
        </Box>
      ))}

      <Box marginTop={1} flexDirection="column">
        {conflicts.some((c) => c.alternative) && (
          <Text color="gray">
            Alternative ports will be used for conflicting services.
          </Text>
        )}
        <Box marginTop={1}>
          <Text>
            <Text color="green" bold>
              Enter
            </Text>
            {" to continue with alternatives  "}
            <Text color="yellow" bold>
              Escape
            </Text>
            {" to abort"}
          </Text>
        </Box>
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
      <Text>Where should we clone the repository?</Text>
      <Box>
        <Text color={THEME_COLOR}>➜ </Text>
        <TextInput value={value} onChange={setValue} onSubmit={onSubmit} />
      </Box>
      <Text color="gray">(Press Enter for default: {defaultValue})</Text>
    </Box>
  );
};

const FinishedStep: React.FC<{
  servicesAlreadyRunning?: boolean;
  onConfirm: () => void;
}> = ({ servicesAlreadyRunning, onConfirm }) => {
  useInput((_input, key) => {
    if (key.return) {
      onConfirm();
    }
  });

  return (
    <Box
      flexDirection="column"
      marginTop={2}
      borderStyle="round"
      borderColor={THEME_COLOR}
      padding={1}
    >
      <Text color={THEME_COLOR} bold>
        You are all set!
      </Text>
      {servicesAlreadyRunning && (
        <Box marginTop={1} flexDirection="column">
          <Text color="green">Services are already running:</Text>
          <Box marginLeft={2} flexDirection="column">
            <Text>
              Web:{" "}
              <Text color="cyan" bold>
                http://localhost:3000
              </Text>
            </Text>
            <Text>
              API:{" "}
              <Text color="cyan" bold>
                http://localhost:8000
              </Text>
            </Text>
          </Box>
        </Box>
      )}
      <CommandsSummary />
      <Box marginTop={1}>
        <Text dimColor>Press Enter to exit</Text>
      </Box>
    </Box>
  );
};

export const CommandsSummary: React.FC = () => (
  <Box marginTop={1} flexDirection="column">
    <Text bold>Available commands:</Text>
    <Box marginLeft={2} flexDirection="column">
      <Text>
        <Text color={THEME_COLOR} bold>gaia start </Text>
        <Text color="gray"> Start all services</Text>
      </Text>
      <Text>
        <Text color={THEME_COLOR} bold>gaia stop  </Text>
        <Text color="gray"> Stop all services</Text>
      </Text>
      <Text>
        <Text color={THEME_COLOR} bold>gaia status</Text>
        <Text color="gray"> Check service health</Text>
      </Text>
      <Text>
        <Text color={THEME_COLOR} bold>gaia setup </Text>
        <Text color="gray"> Reconfigure environment</Text>
      </Text>
    </Box>
  </Box>
);

// Dependency installation progress step
const DependencyInstallStep: React.FC<{
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

        {/* Logs Window */}
        {!isComplete && logs && logs.length > 0 && (
          <Box
            flexDirection="column"
            marginTop={1}
            borderStyle="single"
            borderColor="gray"
            paddingX={1}
            paddingY={0}
            minHeight={6}
          >
            {logs.map((log, i) => (
              <Text key={i} color="gray" wrap="truncate">{log}</Text>
            ))}
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

      <Box
        flexDirection="column"
        marginTop={1}
        padding={1}
        borderStyle="single"
        borderColor="gray"
      >
        <Text dimColor>Command that will run:</Text>
        {setupMode === "selfhost" ? (
          <Box flexDirection="column">
            <Text color="cyan">$ docker compose --profile all up -d</Text>
            <Text color="cyan">$ nx build web</Text>
            <Text color="cyan">$ nx start web</Text>
          </Box>
        ) : (
            <Box flexDirection="column">
              <Text color="cyan">$ cd {repoPath}</Text>
              <Text color="cyan">$ mise dev</Text>
            </Box>
        )}
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text>
          <Text color="green" bold>
            Enter
          </Text>{" "}
          to start GAIA{"  •  "}
          <Text color="yellow" bold>
            Escape
          </Text>{" "}
          to skip and see manual commands
        </Text>
      </Box>
    </Box>
  );
};

// Services running success step
export const ServicesRunningStep: React.FC<{
  setupMode: SetupMode;
  onConfirm: () => void;
}> = ({ setupMode, onConfirm }) => {
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
      <Box marginBottom={1}>
        <Text bold color={THEME_COLOR}>
          GAIA is Running!
        </Text>
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text color="green">✓ Docker services started successfully</Text>
        <Text color="green">✓ API server running</Text>
        <Text color="green">✓ Web frontend running</Text>
        {setupMode === "selfhost" && (
          <Text color="green">✓ Background workers running</Text>
        )}
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text>Access GAIA at:</Text>
        <Box marginLeft={2} flexDirection="column">
          <Text>
            Web:{" "}
            <Text color="cyan" bold>
              http://localhost:3000
            </Text>
          </Text>
          <Text>
            API:{" "}
            <Text color="cyan" bold>
              http://localhost:8000
            </Text>
          </Text>
        </Box>
      </Box>

      <CommandsSummary />

      <Box marginTop={1}>
        <Text dimColor>Press Enter to exit</Text>
      </Box>
    </Box>
  );
};

// Manual commands display (shown when user skips auto-start)
export const ManualCommandsStep: React.FC<{
  setupMode: SetupMode;
  repoPath: string;
  onConfirm: () => void;
}> = ({ setupMode, repoPath, onConfirm }) => {
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
      <Box marginBottom={1}>
        <Text bold color={THEME_COLOR}>
          Setup Complete!
        </Text>
      </Box>

      <Box flexDirection="column" marginBottom={1}>
        <Text>To start GAIA, run:</Text>
      </Box>

      <Box
        flexDirection="column"
        padding={1}
        borderStyle="single"
        borderColor="gray"
      >
        {setupMode === "selfhost" ? (
          <Box flexDirection="column">
            <Text color="cyan">$ docker compose --profile all up -d</Text>
            <Text color="cyan">$ nx build web</Text>
            <Text color="cyan">$ nx start web</Text>
          </Box>
        ) : (
            <Box flexDirection="column">
              <Text color="cyan">$ cd {repoPath}</Text>
              <Text color="cyan">$ mise dev</Text>
            </Box>
        )}
      </Box>

      <CommandsSummary />

      <Box marginTop={1}>
        <Text dimColor>Press Enter to exit</Text>
      </Box>
    </Box>
  );
};

export const SetupModeSelectionStep: React.FC<{
  onSelect: (mode: SetupMode) => void;
}> = ({ onSelect }) => {
  const options = [
    {
      label: "Self-Host (Docker)",
      value: "selfhost",
    },
    {
      label: "Developer Mode (Local)",
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
      <Box marginTop={1} flexDirection="column">
        <Text color="gray" dimColor>
          Self-Host: Run everything in Docker containers (recommended for
          deployment)
        </Text>
        <Text color="gray" dimColor>
          Developer: Run backend locally with Docker services (recommended for
          contributing)
        </Text>
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
          Infisical: Use Infisical for secret management (requires setup)
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

  const currentField = fields[activeIndex];

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
                      ? "✓ " + "*".repeat(8)
                      : "✓ " + values[field.key]
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
        <Text color="gray" dimColor>
          ↑↓/Tab to navigate • Enter to confirm
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
        prev < category.variables.length - 1 ? prev + 1 : prev
      );
    } else if (key.upArrow) {
      // Move to previous field
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : prev));
    } else if (key.escape) {
      // Skip entire group if no required fields are empty
      const missingRequired = category.variables.filter(
        (v) => v.required && !values[v.name]?.trim()
      );
      if (missingRequired.length > 0) {
        setError(
          `Required fields cannot be skipped: ${missingRequired.map((v) => v.name).join(", ")}`
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
        (v) => v.required && !values[v.name]?.trim()
      );
      if (missingRequired.length > 0) {
        setError(
          `Required fields are missing: ${missingRequired.map((v) => v.name).join(", ")}`
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

      {/* Group Info */}
      <Box marginTop={1} flexDirection="column">
        <Box>
          <Text color="cyan" bold>
            Purpose:{" "}
          </Text>
          <Text color="white">{category.description}</Text>
        </Box>

        {category.affectedFeatures && (
          <Box>
            <Text color="cyan" bold>
              Affects:{" "}
            </Text>
            <Text color="gray">{category.affectedFeatures}</Text>
          </Box>
        )}

        {category.docsUrl && (
          <Box marginTop={1}>
            <Text color="green">📖 Docs: </Text>
            <Text color="blue" underline>
              {category.docsUrl}
            </Text>
          </Box>
        )}
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

      {/* Help Text */}
      <Box marginTop={1} flexDirection="column">
        <Text color="gray" dimColor>
          ↵ Enter to next field • Tab/↓ move down • ↑ move up
          {!hasAnyRequired && " • ESC skip group"}
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
  /** Callback when user selects and configures an alternative */
  onSubmit: (selectedGroup: string, values: Record<string, string>) => void;
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
    new Set()
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
  }, []);

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
    let hasConfiguredProvider = false;
    let configuredGroup = "";
    const configuredValues: Record<string, string> = {};

    for (const catIdx of enabledProviders) {
      const category = alternatives[catIdx];
      if (!category) continue;

      const hasValue = category.variables.some((v) =>
        allValues[v.name]?.trim()
      );
      if (hasValue) {
        hasConfiguredProvider = true;
        configuredGroup = category.name;
        // Collect values from this provider
        for (const v of category.variables) {
          const val = allValues[v.name];
          if (val) {
            configuredValues[v.name] = val;
          }
        }
      }
    }

    if (!hasConfiguredProvider) {
      if (enabledProviders.size === 0) {
        setError("Enable at least one provider (press Space or Enter)");
      } else {
        setError("Enter a value for at least one field");
      }
      return;
    }

    onSubmit(configuredGroup, configuredValues);
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
            (item) => item.type === "provider" && item.categoryIndex === catIdx
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
                        item.fieldIndex === fieldIdx
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

  useInput((input, key) => {
    if (key.escape || input === "s") {
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
        <Text bold>Configure Environment Variables</Text>
        <Text color="gray">
          {currentIndex + 1} / {totalCount}
        </Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        {/* Variable Name */}
        <Box>
          <Text color={THEME_COLOR} bold>
            {currentVar.name}
          </Text>
          {currentVar.required ? (
            <Text color="red" bold>
              {" "}
              * required
            </Text>
          ) : (
            <Text color="gray" dimColor>
              {" "}
              (optional)
            </Text>
          )}
        </Box>

        {/* Category */}
        <Box marginTop={1}>
          <Text color="cyan" bold>
            Category:{" "}
          </Text>
          <Text color="white">{currentVar.category}</Text>
        </Box>

        {/* Purpose/Description */}
        <Box>
          <Text color="cyan" bold>
            Purpose:{" "}
          </Text>
          <Text color="white">{currentVar.description}</Text>
        </Box>

        {/* Affected Features */}
        {currentVar.affectedFeatures && (
          <Box>
            <Text color="cyan" bold>
              Affects:{" "}
            </Text>
            <Text color="gray">{currentVar.affectedFeatures}</Text>
          </Box>
        )}

        {/* Documentation Link */}
        {currentVar.docsUrl && (
          <Box marginTop={1}>
            <Text color="green">📖 Docs: </Text>
            <Text color="blue" underline>
              {currentVar.docsUrl}
            </Text>
          </Box>
        )}

        {/* Default Value */}
        {hasDefault && (
          <Box marginTop={1}>
            <Text color="green" bold>
              Default:{" "}
            </Text>
            <Text color="white">{currentVar.defaultValue}</Text>
          </Box>
        )}
      </Box>

      {/* Input */}
      <Box marginTop={1}>
        <Text color={THEME_COLOR}>➜ </Text>
        <TextInput
          value={value}
          onChange={(newValue) => {
            setValue(newValue);
            if (error) setError(null);
          }}
          onSubmit={handleSubmit}
          placeholder={
            hasDefault
              ? "Press Enter to use default"
              : currentVar.required
                ? "Enter a value (required)"
                : "Press Enter to skip"
          }
        />
      </Box>

      {/* Error Message */}
      {error && (
        <Box marginTop={1}>
          <Text color="red" bold>
            ⚠ {error}
          </Text>
        </Box>
      )}

      {/* Help Text */}
      <Box marginTop={1} flexDirection="column">
        {currentVar.required ? (
          <Text color="yellow" dimColor>
            ↵ Enter to confirm (required field)
          </Text>
        ) : hasDefault ? (
          <Text color="green" dimColor>
            ↵ Enter to use default • ESC to skip
          </Text>
        ) : (
          <Text color="gray" dimColor>
            ↵ Enter to confirm • ESC to skip
          </Text>
        )}
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

  return (
    <Shell status={state.status} step={state.step}>
      {state.step === "Welcome" && state.inputRequest?.id === "welcome" && (
        <WelcomeStep onConfirm={() => store.submitInput(true)} />
      )}

      {state.step === "Prerequisites" && state.data.checks && (
        <Box
          flexDirection="column"
          borderStyle="round"
          paddingX={1}
          borderColor={THEME_COLOR}
        >
          <Text bold>System Checks</Text>
          <Box flexDirection="column" marginTop={1}>
            <CheckItem label="Git" status={state.data.checks.git} />
            <CheckItem label="Docker" status={state.data.checks.docker} />
            <CheckItem label="Mise" status={state.data.checks.mise} />
          </Box>
        </Box>
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

      {state.step === "Repository Setup" && (
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
            onSubmit={(selectedGroup, values) =>
              store.submitInput({ selectedGroup, values })
            }
          />
        )}

      {state.step === "Finished" && (
        <FinishedStep
          servicesAlreadyRunning={state.data.servicesAlreadyRunning}
          onConfirm={() => store.submitInput(true)}
        />
      )}

      {(state.step === "Install Tools" || state.step === "Project Setup") && (
        <DependencyInstallStep
          title={state.step === "Install Tools" ? "Installing Tools" : "Project Setup"}
          phase={state.data.dependencyPhase || ""}
          progress={state.data.dependencyProgress || 0}
          isComplete={state.data.dependencyComplete || false}
          logs={state.data.dependencyLogs || []}
        />
      )}

      {state.inputRequest?.id === "start_services" && (
        <StartServicesStep
          setupMode={state.data.setupMode || "developer"}
          repoPath={state.data.repoPath || "./gaia"}
          onStart={() => store.submitInput("start")}
          onSkip={() => store.submitInput("skip")}
        />
      )}

      {state.inputRequest?.id === "manual_commands" && (
        <ManualCommandsStep
          setupMode={state.data.setupMode || "developer"}
          repoPath={state.data.repoPath || "./gaia"}
          onConfirm={() => store.submitInput(true)}
        />
      )}

      {state.inputRequest?.id === "services_running" && (
        <ServicesRunningStep
          setupMode={state.data.setupMode || "developer"}
          onConfirm={() => store.submitInput(true)}
        />
      )}

      {state.error && (
        <Box borderStyle="single" borderColor="red" padding={1} marginTop={2}>
          <Text color="red">Error: {state.error.message}</Text>
        </Box>
      )}
    </Shell>
  );
};
