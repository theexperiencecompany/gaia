/**
 * `gaia up` — one-command self-hosted setup.
 *
 * Flow: make Docker available (one install offer) → check the release's
 * images exist for this computer → resolve the install (recorded, or this
 * release's setup files downloaded; a source clone only for --build) →
 * env-setup selfhost pipeline with pre-sourced answers (flags → saved config →
 * defaults) → download the images → start → wait for GAIA to answer → save a
 * flagged AI provider → the summary card. Each phase is one step on screen.
 * @module commands/up/flow
 */

import { execFile } from "node:child_process";
import * as os from "node:os";
import type { SetupStatusResponse } from "@gaia/shared/api/generated";
import {
  createUpAnswerResolver,
  DEFAULT_INSTALL_DIR,
  pinnedPorts,
  portConflictPolicy,
  resolveRecordedInstall,
  type UpFlags,
} from "../../lib/answers.js";
import { explainImageGap } from "../../lib/compose-failure.js";
import {
  readConfig,
  recordedLocalName,
  updateConfig,
} from "../../lib/config.js";
import { resumedSteps } from "../../lib/docker-group.js";
import { waitForCertificate } from "../../lib/domain-reachability.js";
import {
  DEFAULT_HTTPS_PORT,
  DEFAULT_WEB_PORT,
  hostWebUrls,
  localApiUrl,
  localhostWebUrl,
  localNameUrl,
  primaryWebUrl,
} from "../../lib/endpoints.js";
import { runEnvSetup } from "../../lib/env-setup.js";
import {
  readDockerComposePortOverrides,
  readGaiaDomain,
  readPinnedGaiaVersion,
} from "../../lib/env-writer.js";
import { runPortChecks } from "../../lib/flow-utils.js";
import { findReleaseImageGap } from "../../lib/image-availability.js";
import {
  assertBuildableInstall,
  isGaiaInstall,
  isSelfhostOrUnconfigured,
} from "../../lib/install-root.js";
import {
  LLM_PROVIDER_NAMES,
  saveLlmProvider,
  validateLlmFlags,
} from "../../lib/llm-flags.js";
import {
  needsLocalCertificate,
  needsPublicCertificate,
} from "../../lib/local-certificate.js";
import {
  type LocalNameAction,
  localNameAction,
  localNameLabel,
  removeLocalName,
  setUpLocalName,
} from "../../lib/local-name.js";
import { homeRelative } from "../../lib/paths.js";
import {
  ensurePrerequisites,
  INSTALL_STAGES,
  joinNames,
  PrerequisiteDeclined,
} from "../../lib/prerequisite-install.js";
import {
  cloneRelease,
  GAIA_REPO_URL,
  pinReleaseImages,
} from "../../lib/release.js";
import {
  advanceSubstep,
  endActiveStep,
  finishStep,
  initSteps,
  skipStep,
  startStep,
  updateStep,
} from "../../lib/run-steps.js";
import { placeBundle, stageBundle } from "../../lib/selfhost-bundle.js";
import { readSetupEndpoint } from "../../lib/setup-endpoints.js";
import {
  downloadReporter,
  imagesStep,
  START_STEP,
  startSelfhostServices,
  waitForGaia,
} from "../../lib/start-steps.js";
import { CLI_VERSION, GAIA_RELEASE_IMAGE_TAG } from "../../lib/version.js";
import type { CLIStore } from "../../ui/store.js";
import { checkHostResources, domainDnsWarning } from "./preflight.js";
import type { UpOutcome } from "./summary.types.js";

/** The command a missing-image error points `gaia up` users to. */
const UP_REBUILD_COMMAND = "gaia up --build";

/** Store key for the one line a run that stopped on the user's answer ends with. */
export const UP_NOTICE_KEY = "upNotice";

/** How an install comes to be: there already, this release's setup files, or (for --build) its source. */
type InstallSource = "existing" | "bundle" | "clone";

/** The steps `gaia up` shows, in order; download, start, the certificate and gaia.local drop out with --no-start. */
function upSteps(
  options: UpFlags,
  source: InstallSource,
  localName: LocalNameAction,
  publicDomain: boolean,
) {
  const provider = options.llmProvider
    ? LLM_PROVIDER_NAMES[options.llmProvider]
    : null;
  const files = {
    existing: {
      label: "Finding your install",
      doneLabel: "Using your install",
      minor: true,
    },
    bundle: {
      label: "Getting GAIA's setup files",
      doneLabel: "Got GAIA's setup files",
      minor: true,
    },
    clone: {
      label: "Downloading GAIA's source",
      doneLabel: "Downloaded GAIA's source",
    },
  }[source];
  return [
    {
      id: "docker",
      label: "Checking Docker",
      doneLabel: "Docker is ready",
      // A Docker that was already there is housekeeping; an install is not, and runs long enough to list.
      minor: true,
    },
    ...(localName === "remove"
      ? [
          {
            id: "local-name-off",
            label: `Removing ${localNameLabel(readConfig()?.localName)}`,
            doneLabel: `Removed ${localNameLabel(readConfig()?.localName)}`,
            minor: true,
          },
        ]
      : []),
    {
      id: "preflight",
      label: "Checking GAIA can run here",
      doneLabel: "GAIA can run here",
      failedLabel: "GAIA can't run here yet",
      minor: true,
    },
    { id: "files", ...files },
    {
      id: "configure",
      label: "Saving your settings",
      doneLabel: "Saved your settings",
      minor: true,
    },
    ...(options.noStart
      ? []
      : [
          imagesStep(options.build === true),
          START_STEP,
          ...(publicDomain
            ? [
                {
                  id: "certificate",
                  label: "Getting the HTTPS certificate",
                  doneLabel: "Got the HTTPS certificate",
                },
              ]
            : []),
          ...(localName === "set-up"
            ? [
                {
                  id: "local-name",
                  label: "Naming GAIA on your network",
                  doneLabel: "Named GAIA on your network",
                  // A rerun only re-checks the name it has: that folds away.
                  minor: true,
                },
              ]
            : []),
        ]),
    ...(provider
      ? [
          {
            id: "provider",
            label: `Checking your ${provider} key`,
            doneLabel: `Saved your ${provider} key`,
          },
        ]
      : []),
  ];
}

/**
 * Where the install comes from: there already, this release's setup files,
 * or for --build its source.
 * @throws Error when --build meets an install of setup files, which has no source to build.
 */
function installSource(targetPath: string, build: boolean): InstallSource {
  if (!isGaiaInstall(targetPath)) return build ? "clone" : "bundle";
  if (build) assertBuildableInstall(targetPath);
  return "existing";
}

function developerTreeError(targetPath: string): Error {
  return new Error(
    `${targetPath} is not a self-host install (its apps/api/.env is in developer mode or names no mode), and 'gaia up' would overwrite its settings.\n` +
      "Run it with --force-dev-tree to go ahead anyway.",
  );
}

/** Record a failure: the running row turns red and the error is shown under the list. */
function fail(store: CLIStore, error: Error): void {
  endActiveStep(store, "failed");
  store.setError(error);
}

export async function runUpFlow(
  store: CLIStore,
  options: UpFlags = {},
): Promise<void> {
  // Fail loud on contradictory flags before any side effect — every message
  // names the flag that fixes it.
  validateLlmFlags(options);
  // A docker-group relaunch continues the first process's run, and its clock.
  const runStartedAt = Math.min(
    Date.now(),
    ...Object.values(resumedSteps()).map((step) => step.startedAt),
  );

  const recordedInstall = resolveRecordedInstall();
  const targetPath = recordedInstall ?? DEFAULT_INSTALL_DIR;
  let source: InstallSource;
  try {
    source = installSource(targetPath, options.build === true);
  } catch (e) {
    store.setError(e as Error);
    return;
  }

  // Seed the values layer BEFORE any waitForInput can block: every prompt the
  // pipeline raises resolves from flags → saved config → defaults.
  store.pushAnswerResolver(createUpAnswerResolver({ repoPath: targetPath }));
  const domain = servedDomain(options, targetPath);
  const localName = plannedLocalName(options, domain);
  initSteps(
    store,
    upSteps(options, source, localName, needsPublicCertificate(domain)),
  );

  // 1. Docker, the release's images, and ports. Only a docker-group relaunch reads the step name;
  // a later setStep would draw the list between two steps with neither running.
  store.setStep("Prerequisites");
  if (!(await prepareDocker(store, options, source))) return;
  finishStep(store, "docker");
  // Before the port checks: a domain needs port 80, which the name's proxy holds.
  if (!(await turnOffLocalName(store, localName))) return;
  startStep(store, "preflight");
  if (
    !options.build &&
    !(await checkReleaseImages(store, targetPath, source !== "existing"))
  ) {
    return;
  }
  const checked = await checkMachine(store, options, {
    targetPath,
    source,
    domain,
  });
  if (!checked) return;
  const { portOverrides, warnings } = checked;

  // Never rewrite a developer-mode checkout's .env; an unconfigured or
  // self-host one (a half-finished first run) is safe to resume.
  if (
    source === "existing" &&
    targetPath !== recordedInstall &&
    !options.forceDevTree &&
    !(await isSelfhostOrUnconfigured(targetPath))
  ) {
    fail(store, developerTreeError(targetPath));
    return;
  }
  if (warnings.length > 0) updateStep(store, "preflight", { warnings });
  finishStep(store, "preflight");

  // 2. The install: the recorded/existing one, else this release's setup files.
  startStep(store, "files");
  if (!(await prepareInstall(store, targetPath, source))) return;
  // Record the install before anything else can fail, so a rerun resumes
  // this checkout instead of tripping over it. The sandbox choice is saved
  // here too: every compose start reads it from the config.
  updateConfig(
    options.codeSandbox === undefined
      ? { repoPath: targetPath }
      : { repoPath: targetPath, codeSandbox: options.codeSandbox },
  );
  finishStep(
    store,
    "files",
    source === "existing"
      ? `Using your install at ${homeRelative(targetPath)}`
      : undefined,
  );

  // 3. Settings — selfhost pipeline with pre-sourced answers.
  startStep(store, "configure");
  await runEnvSetup(store, targetPath, "selfhost", portOverrides, {
    llmProvider: options.llmProvider,
    domain: options.domain,
  });
  if (store.currentState.error) {
    endActiveStep(store, "failed");
    return;
  }
  finishStep(store, "configure");

  const served = servedAt(targetPath);
  const webPort = served.webPort;
  const outcome: UpOutcome = {
    ...webAddresses(webPort, domain),
    noStart: options.noStart === true,
    stillStarting: false,
    setupComplete: false,
    elapsedMs: 0,
    startedServices: 0,
  };
  if (options.noStart) {
    finishUp(store, targetPath, {
      ...outcome,
      elapsedMs: Date.now() - runStartedAt,
    });
    return;
  }

  // 4. Start, then wait for GAIA to answer (a timeout still exits 0).
  try {
    outcome.startedServices = await startSelfhostServices(
      store,
      targetPath,
      portOverrides,
      // A rerun keeps the images it has; `gaia update` refreshes them. A failed
      // start never turns into a build behind the user's back.
      {
        ...(options.build ? { build: true } : { pull: "missing" as const }),
        rebuildCommand: UP_REBUILD_COMMAND,
      },
    );
  } catch (e) {
    fail(store, e as Error);
    return;
  }
  const apiUrl = served.apiUrl;
  const readiness = await waitForGaia(
    store,
    { apiUrl, webPort },
    outcome.startedServices,
  );
  outcome.stillStarting = !readiness.ready;
  outcome.setupComplete = readiness.ready && (await isSetupComplete(apiUrl));
  Object.assign(
    outcome,
    await getCertificate(store, domain, served.httpsPort, readiness.ready),
  );
  Object.assign(
    outcome,
    await nameOnNetwork(store, localName, webPort, readiness.ready),
  );

  // 5. The flagged AI provider, checked by the API's live probe before saving.
  const providerError = await saveFlaggedProvider(
    store,
    targetPath,
    options,
    readiness.ready,
  );
  if (options.llmProvider) {
    if (providerError) outcome.unsavedProvider = options.llmProvider;
    else outcome.savedProvider = options.llmProvider;
  }
  finishUp(store, targetPath, {
    ...outcome,
    elapsedMs: Date.now() - runStartedAt,
  });
  if (providerError) {
    store.setError(providerError);
    return;
  }
  if (readiness.ready) openSetupWizard(outcome.webUrl, options);
}

/**
 * The machine half of the preflight: memory and disk, the ports this run
 * binds, and a domain's DNS. Returns null after recording why the run stops.
 */
async function checkMachine(
  store: CLIStore,
  options: UpFlags,
  install: { targetPath: string; source: InstallSource; domain?: string },
): Promise<{
  portOverrides: Record<number, number>;
  warnings: string[];
} | null> {
  const { targetPath, source, domain } = install;
  const warnings: string[] = [];
  const resources = await checkHostResources(
    source === "existing" ? "run" : "install",
  ).catch((e: Error) => ({
    blocker: `Couldn't check this machine's memory and disk space: ${e.message}`,
    warnings: [],
  }));
  if (resources.blocker) {
    fail(store, new Error(resources.blocker));
    return null;
  }
  warnings.push(...resources.warnings);
  // The ports this run binds: earlier runs' choices, then what the flags (or a saved domain) pin.
  const pinned = pinnedPorts({
    webPort: options.webPort,
    domain: options.domain === false ? false : domain,
  });
  const recorded = readDockerComposePortOverrides(targetPath);
  const recordedWebPort = recorded[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  if (
    pinned.fixed[DEFAULT_WEB_PORT] === "domain" &&
    recordedWebPort !== pinned.planned[DEFAULT_WEB_PORT]
  ) {
    warnings.push(
      `A domain is served on ports 80 and 443, so GAIA moves from port ${recordedWebPort} to 80 and 443.`,
    );
  }
  const ports = await runPortChecks(store, "selfhost", {
    planned: { ...recorded, ...pinned.planned },
    fixed: pinned.fixed,
    policy: portConflictPolicy(options),
  });
  if (ports === null) {
    endActiveStep(store, "failed");
    return null;
  }
  const portOverrides = ports.overrides;
  warnings.push(...ports.moved);
  if (needsPublicCertificate(domain)) {
    const dnsWarning = await domainDnsWarning(domain);
    if (dnsWarning) warnings.push(dnsWarning);
  }

  return { portOverrides, warnings };
}

/**
 * Make Docker available, installing it with consent. Returns false when the
 * run stops here: a failure, a declined install (one line saying so), or a
 * relaunch into the docker group.
 */
async function prepareDocker(
  store: CLIStore,
  options: UpFlags,
  source: InstallSource,
): Promise<boolean> {
  startStep(store, "docker");
  try {
    const readiness = await ensurePrerequisites(store, {
      needGit: source === "clone",
      assumeYes: options.yes === true,
      rerunCommand: "gaia up",
      // The clock restarts here: time spent reading the question is not install time.
      onInstallStart: (missing) =>
        startStep(store, "docker", {
          label: `Installing ${joinNames(missing)}`,
          doneLabel: `${joinNames(missing)} installed`,
          startedAt: Date.now(),
        }),
      onInstallProgress: (progress) =>
        advanceSubstep(
          store,
          "docker",
          INSTALL_STAGES,
          progress.stage,
          progress.note,
        ),
    });
    return readiness !== "relaunch";
  } catch (e) {
    if (!(e instanceof PrerequisiteDeclined)) {
      fail(store, e as Error);
      return false;
    }
    skipStep(store, "docker");
    store.updateData(UP_NOTICE_KEY, e.message);
    process.exitCode = 1;
    return false;
  }
}

/** The domain this run serves: --domain, else the one an earlier run set, none on --no-domain. */
function servedDomain(
  options: UpFlags,
  targetPath: string,
): string | undefined {
  if (options.domain === false) return undefined;
  return options.domain ?? readGaiaDomain(targetPath);
}

/** What this run does about gaia.local, from its flags, the install's domain and the last run. */
function plannedLocalName(
  options: UpFlags,
  domain: string | undefined,
): LocalNameAction {
  return localNameAction({
    optedOut: options.localName === false,
    domain,
    setUpBefore: Boolean(readConfig()?.localName),
  });
}

/**
 * Where the install now serves GAIA: the compose env file holds this run's port
 * flags and every earlier run's choice (a domain's port 80), as compose reads it.
 */
function servedAt(targetPath: string): {
  webPort: number;
  httpsPort: number;
  apiUrl: string;
} {
  const ports = readDockerComposePortOverrides(targetPath);
  return {
    webPort: ports[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT,
    httpsPort: ports[DEFAULT_HTTPS_PORT] ?? DEFAULT_HTTPS_PORT,
    apiUrl: localApiUrl("selfhost", ports),
  };
}

/** Wait for the domain's certificate under its own step; returns why it isn't there, if it isn't. */
async function getCertificate(
  store: CLIStore,
  domain: string | undefined,
  httpsPort: number,
  ready: boolean,
): Promise<Pick<UpOutcome, "certificateProblem">> {
  if (!needsPublicCertificate(domain)) return {};
  startStep(store, "certificate");
  // A GAIA that never answered has its own row on the card; its proxy may not be up to ask.
  if (!ready) {
    skipStep(store, "certificate");
    return {};
  }
  const problem = await waitForCertificate(domain, httpsPort);
  if (problem === null) {
    finishStep(store, "certificate");
    return {};
  }
  updateStep(store, "certificate", { state: "failed", endedAt: Date.now() });
  return { certificateProblem: problem };
}

/**
 * Where the card sends a browser, and whether the domain's certificate is a
 * local one. A domain's proxy redirects LAN addresses to HTTPS, so none are listed.
 */
function webAddresses(
  webPort: number,
  domain: string | undefined,
): Pick<UpOutcome, "webUrl" | "localhostUrl" | "lanUrls" | "localCertificate"> {
  return {
    webUrl: primaryWebUrl(webPort, domain),
    localhostUrl: localhostWebUrl(webPort),
    lanUrls: domain ? [] : hostWebUrls(webPort),
    localCertificate: domain !== undefined && needsLocalCertificate(domain),
  };
}

/**
 * Remove the gaia.local name an earlier run set up, when this run drops it.
 * Returns false after recording the error.
 */
async function turnOffLocalName(
  store: CLIStore,
  localName: LocalNameAction,
): Promise<boolean> {
  if (localName !== "remove") return true;
  const name = localNameLabel(readConfig()?.localName);
  startStep(store, "local-name-off");
  try {
    await removeLocalName();
  } catch (e) {
    fail(store, new Error(`Couldn't remove ${name}: ${(e as Error).message}`));
    return false;
  }
  updateConfig({ localName: undefined });
  finishStep(store, "local-name-off");
  return true;
}

/**
 * Name GAIA gaia.local for other devices on the network. Never fails the run:
 * a problem becomes one warning line on the card.
 */
async function nameOnNetwork(
  store: CLIStore,
  localName: LocalNameAction,
  webPort: number,
  ready: boolean,
): Promise<Pick<UpOutcome, "localUrl" | "localNameProblem">> {
  if (localName !== "set-up") return {};
  startStep(store, "local-name");
  if (!ready) {
    skipStep(store, "local-name");
    return {
      localNameProblem:
        "GAIA didn't answer in time; run 'gaia up' again once 'gaia status' shows it running",
    };
  }
  const recorded = readConfig()?.localName;
  // Marked first, so a half-finished setup is still removed later.
  if (!recorded) updateConfig({ localName: true });
  let name: string;
  try {
    name = await setUpLocalName(
      webPort,
      recordedLocalName(recorded),
      (detail) => updateStep(store, "local-name", { detail }),
    );
  } catch (e) {
    skipStep(store, "local-name");
    return { localNameProblem: (e as Error).message };
  }
  updateConfig({ localName: name });
  finishStep(store, "local-name", `${name}.local set up`);
  return { localUrl: localNameUrl(name) };
}

/**
 * Fail in seconds, not after a clone, when the release cannot run on this
 * computer. Returns false after recording the error.
 */
async function checkReleaseImages(
  store: CLIStore,
  targetPath: string,
  needsClone: boolean,
): Promise<boolean> {
  const tag = needsClone
    ? GAIA_RELEASE_IMAGE_TAG
    : readPinnedGaiaVersion(targetPath);
  store.setStatus(`Checking that GAIA ${tag} is available for this computer…`);
  const gap = await findReleaseImageGap(tag, readConfig()?.bots ?? []);
  if (!gap) return true;
  const { cause, next } = explainImageGap(gap, UP_REBUILD_COMMAND);
  fail(store, new Error(`${cause}\n${next}`));
  return false;
}

/**
 * Lay this CLI's release into a fresh install: its setup files, or for
 * --build a clone of its source. Returns false after recording the error.
 */
async function prepareInstall(
  store: CLIStore,
  targetPath: string,
  source: InstallSource,
): Promise<boolean> {
  if (source === "existing") return true;
  try {
    if (source === "bundle") {
      const staged = await stageBundle(
        targetPath,
        GAIA_RELEASE_IMAGE_TAG,
        downloadReporter(store, "files"),
      );
      await placeBundle(staged.manifest, staged.stagingDir, targetPath, []);
      pinReleaseImages(targetPath, GAIA_RELEASE_IMAGE_TAG);
      return true;
    }
    updateStep(store, "files", { detail: "Connecting to GitHub…" });
    await cloneRelease(targetPath, GAIA_REPO_URL, (percent, phase) => {
      updateStep(
        store,
        "files",
        phase ? { percent, detail: phase } : { percent },
      );
    });
  } catch (e) {
    fail(
      store,
      new Error(
        `Couldn't get GAIA into ${homeRelative(targetPath)}: ${(e as Error).message}`,
      ),
    );
    return false;
  }
  return true;
}

/** macOS's opener by absolute path, so a writable PATH entry cannot shadow it. */
const MACOS_OPEN = "/usr/bin/open";

/**
 * Auto-open the setup wizard when running interactively on macOS. Non-blocking,
 * errors are ignored: the URL is already printed on the success screen and in
 * the plain summary.
 */
function openSetupWizard(webUrl: string, options: UpFlags): void {
  const isTTY = process.stdin.isTTY === true && process.stdout.isTTY === true;
  if (!options.yes && isTTY && os.platform() === "darwin") {
    execFile(MACOS_OPEN, [`${webUrl}/setup`], () => undefined);
  }
}

/**
 * Save the `--llm-provider` the run was given into the now-running instance.
 * Returns the error to show when it was not saved, else null.
 */
async function saveFlaggedProvider(
  store: CLIStore,
  repoPath: string,
  options: UpFlags,
  ready: boolean,
): Promise<Error | null> {
  const { llmProvider } = options;
  if (!llmProvider) return null;
  const name = LLM_PROVIDER_NAMES[llmProvider];
  startStep(store, "provider");
  if (!ready) {
    endActiveStep(store, "failed");
    return new Error(
      `GAIA didn't answer in time, so your ${name} key wasn't saved.\n` +
        "Once 'gaia status' shows it running, run 'gaia up' again with the same flags.",
    );
  }
  try {
    await saveLlmProvider(repoPath, { ...options, llmProvider });
  } catch (e) {
    endActiveStep(store, "failed");
    return new Error(
      `Your ${name} key wasn't saved: ${(e as Error).message}\n` +
        `Check the key and run 'gaia up --llm-provider ${llmProvider} --llm-key <key>' again, or add it on the setup page above.`,
    );
  }
  finishStep(store, "provider");
  return null;
}

/**
 * Whether the browser wizard has nothing left to do (an admin and a working
 * AI provider exist). An unreadable status counts as not complete, so the
 * summary keeps pointing at the wizard.
 */
async function isSetupComplete(apiUrl: string): Promise<boolean> {
  const status = await readSetupEndpoint<SetupStatusResponse>(apiUrl, "status");
  return "data" in status && !status.data.needs_setup;
}

/** Record the install and hand the outcome to the summary card. */
function finishUp(store: CLIStore, repoPath: string, outcome: UpOutcome): void {
  // A partial update: the saved sandbox choice must survive a finished run.
  updateConfig({
    version: CLI_VERSION,
    setupComplete: true,
    setupMethod: store.currentState.data.envMethod ?? "manual",
    repoPath,
  });
  store.updateData("setupMode", "selfhost");
  store.updateData("upOutcome", outcome);
  store.updateData("finished", true);
  store.setStep("Finished");
}
