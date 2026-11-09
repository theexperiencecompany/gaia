/**
 * What the CLI store holds: every data key a flow writes and a screen reads,
 * and every input a flow asks for, with its meta and its answer.
 * @module ui/store.types
 */

import type { CredentialRequest } from "../commands/bots/prompt.js";
import type { DoctorReport } from "../commands/doctor/flow.js";
import type { StatusFacts } from "../commands/status/report.types.js";
import type { UninstallOutcome } from "../commands/uninstall/flow.js";
import type { UpOutcome } from "../commands/up/summary.types.js";
import type { UpdateOffer } from "../commands/update/offer.js";
import type { CommandEnding } from "../lib/command-ending.js";
import type { EnvMethod } from "../lib/config.js";
import type { DockerGroupSwitch } from "../lib/docker-group.js";
import type {
  EnvCategory,
  EnvVar,
  SetupMode,
} from "../lib/env-parser.types.js";
import type { InstallablePrerequisite } from "../lib/prerequisite-install.types.js";
import type {
  CheckResult,
  PortCheckResult,
} from "../lib/prerequisites.types.js";
import type { RunStep } from "../lib/run-steps.js";

/** The prerequisite rows `gaia init` / `gaia setup` show while checking. */
export interface SystemChecks {
  git?: CheckResult;
  docker?: CheckResult;
  mise?: CheckResult;
}

export interface CLIData {
  steps: RunStep[];
  ending: CommandEnding;
  handedOver: boolean;
  checks: SystemChecks;
  missingPrerequisites: readonly InstallablePrerequisite[];
  dockerGroupSwitch: DockerGroupSwitch;
  portConflicts: PortCheckResult[];
  portOverrides: Record<number, number>;
  setupMode: SetupMode;
  envMethod: EnvMethod;
  alternativeGroups: EnvCategory[];
  currentEnvVar: EnvVar;
  envVarIndex: number;
  envVarTotal: number;
  currentEnvGroup: EnvCategory;
  envGroupIndex: number;
  envGroupTotal: number;
  repoPath: string;
  existingRepoPath: string;
  repoPhase: string;
  repoProgress: number;
  dependencyPhase: string;
  dependencyProgress: number;
  dependencyComplete: boolean;
  dependencyLogs: string[];
  toolComplete: boolean;
  stillStarting: boolean;
  installDir: string | null;
  cancelled: boolean;
  finished: boolean;
  upOutcome: UpOutcome;
  upNotice: string;
  updateOffer: UpdateOffer | undefined;
  updateNotice: string;
  doctorReport: DoctorReport;
  statusFacts: StatusFacts;
  uninstallOutcome: UninstallOutcome;
  checkedAt: string;
  watch: boolean;
}

/** What `gaia init` does with a checkout already at the chosen path. */
export type ExistingRepoAction =
  | "use_existing"
  | "delete_reclone"
  | "different_path"
  | "exit";

export interface InfisicalCredentials {
  INFISICAL_PROJECT_ID: string;
  INFISICAL_MACHINE_IDENTITY_CLIENT_ID: string;
  INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET: string;
}

/** The providers picked from a pair of alternatives, and the values entered for them. */
export interface AlternativesAnswer {
  selectedGroups: string[];
  values: Record<string, string>;
}

/**
 * Every input a flow waits for: the meta its screen is given (args: [] when
 * none, so callers pass nothing) and the answer it gets back.
 */
export interface CLIInputs {
  welcome: { args: []; answer: true };
  exit: { args: []; answer: "exit" };
  exit_or_refresh: { args: []; answer: "exit" | "refresh" };
  prerequisite_install_confirm: { args: []; answer: "install" | "decline" };
  port_conflicts: { args: []; answer: "accept" | "abort" };
  repo_path: { args: [meta: { default: string }]; answer: string };
  existing_repo: { args: []; answer: ExistingRepoAction };
  setup_mode: { args: []; answer: SetupMode };
  env_method: { args: []; answer: EnvMethod };
  env_infisical: { args: []; answer: InfisicalCredentials };
  env_alternatives: { args: []; answer: AlternativesAnswer };
  env_var: { args: [meta: { varName: string }]; answer: string };
  env_group: {
    args: [meta: { groupName: string }];
    answer: Record<string, string>;
  };
  bot_credential: { args: [meta: CredentialRequest]; answer: string };
  update_confirm: { args: []; answer: boolean };
  uninstall_confirm: { args: []; answer: boolean };
  uninstall_delete_data: { args: []; answer: boolean };
  uninstall_backup: { args: []; answer: boolean };
}

export type InputId = keyof CLIInputs;
export type InputArgs<K extends InputId> = CLIInputs[K]["args"];
export type InputMeta<K extends InputId> = InputArgs<K>[0];
export type InputAnswer<K extends InputId> = CLIInputs[K]["answer"];

type InputRequestById<Ids extends InputId> = {
  [K in Ids]: { id: K; meta: InputMeta<K> };
};

/** The input a screen is answering; checking its id narrows its meta. */
export type InputRequest<K extends InputId = InputId> = InputRequestById<K>[K];

/**
 * A values layer for inputs: an answer per id (flags, saved config, defaults),
 * or undefined to fall through to the next layer and then the prompt.
 */
export type AnswerResolver = {
  [K in InputId]?: (...args: InputArgs<K>) => InputAnswer<K> | undefined;
};

/** Answers given without asking, e.g. a plain-output run's trailing prompt. */
export type PresetAnswers = { [K in InputId]?: InputAnswer<K> };
