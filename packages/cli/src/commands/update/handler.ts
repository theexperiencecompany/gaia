/**
 * Handler for `gaia update` — say whether a newer release is available here,
 * confirm, apply — as steps on the shared run screen.
 * @module commands/update/handler
 */

import { setEnding } from "../../lib/command-ending.js";
import { runCommandUI } from "../../lib/command-runner.js";
import { explainImageGap } from "../../lib/compose-failure.js";
import { readConfig } from "../../lib/config.js";
import {
  DEFAULT_WEB_PORT,
  installWebUrl,
  localApiUrl,
} from "../../lib/endpoints.js";
import {
  readDockerComposePortOverrides,
  readPinnedGaiaVersion,
} from "../../lib/env-writer.js";
import { findReleaseImageGap } from "../../lib/image-availability.js";
import { findInstallRoot } from "../../lib/install-root.js";
import { isInteractive } from "../../lib/non-tty.js";
import { newerReleaseEnding } from "../../lib/release.js";
import { fetchReleaseHighlights } from "../../lib/release-notes.js";
import {
  endActiveStep,
  finishStep,
  initSteps,
  STEPS_KEY,
  startStep,
} from "../../lib/run-steps.js";
import {
  composePhaseReporter,
  downloadReporter,
  imagesStep,
  START_STEP,
  waitForGaia,
} from "../../lib/start-steps.js";
import {
  displayTag,
  isNewerRelease,
  releaseVersion,
} from "../../lib/update-check.js";
import { CLI_VERSION, GAIA_RELEASE_IMAGE_TAG } from "../../lib/version.js";
import type { CLIStore } from "../../ui/store.js";
import {
  applyGitUpdate,
  applyReleaseUpdate,
  decideReleaseUpdate,
  isReleaseCurrent,
  planGitUpdate,
  planReleaseUpdate,
} from "./flow.js";
import type { ReleasePlan, UpdateReporter, UpdateStage } from "./flow.types.js";
import {
  UPDATE_CONFIRM_INPUT,
  UPDATE_NOTICE_KEY,
  UPDATE_OFFER_KEY,
  type UpdateOffer,
} from "./offer.js";

export interface UpdateOptions {
  yes?: boolean;
  /** Image tag to pin instead of the one this CLI release ships. */
  version?: string;
  /** Developer checkouts: pull the branch and rebuild from source. */
  git?: boolean;
  /** --git: list every new commit, not the first few. */
  verbose?: boolean;
}

const MAX_LISTED_COMMITS = 5;
const RELEASE_NOTES_URL = "https://docs.heygaia.io/release-notes";

const CHECK_STEP = {
  id: "check",
  label: "Checking for updates",
  doneLabel: "Checked for updates",
};

function fail(store: CLIStore, error: Error): void {
  endActiveStep(store, "failed");
  store.setError(error);
}

/**
 * Show the offer and ask, unless --yes; a run without a terminal and without
 * --yes only reports. A "no" leaves one line saying how to update later.
 */
async function confirmed(
  store: CLIStore,
  options: UpdateOptions,
  offer: UpdateOffer,
): Promise<boolean> {
  if (options.yes) return true;
  const later = "Not updated. Run 'gaia update' again when you're ready.";
  if (!isInteractive()) {
    store.updateData(
      UPDATE_NOTICE_KEY,
      "Not updated: rerun with --yes to apply.",
    );
    return false;
  }
  store.updateData(UPDATE_OFFER_KEY, offer);
  const answer = await store.waitForInput(UPDATE_CONFIRM_INPUT);
  store.updateData(UPDATE_OFFER_KEY, undefined);
  if (answer === true) return true;
  store.updateData(UPDATE_NOTICE_KEY, later);
  return false;
}

/** The release's highlights from GitHub; an unreadable release says so in one line. */
async function highlightsOf(tag: string): Promise<string[]> {
  try {
    return await fetchReleaseHighlights(tag);
  } catch (error) {
    return [`(couldn't read what's new: ${(error as Error).message})`];
  }
}

function offerHeadline(plan: ReleasePlan, downgrade: boolean): string {
  const { fromVersion, toVersion, layout } = plan;
  if (fromVersion === toVersion && layout.kind === "checkout") {
    return `GAIA ${toVersion} runs from a git checkout. Move it to the release's setup files, so it no longer needs git?`;
  }
  if (downgrade) return `Switch GAIA ${fromVersion} back to ${toVersion}?`;
  return `Update GAIA ${fromVersion} to ${toVersion}?`;
}

/** Each stage ends the one before it and starts its own step; compose phases drive the image and start steps. */
function stepReporter(store: CLIStore): UpdateReporter {
  const onCompose = composePhaseReporter(store);
  return {
    onStage: (stage: UpdateStage) => {
      const steps = store.currentState.data[STEPS_KEY] ?? [];
      const active = steps.find((step) => step.state === "active");
      if (active && active.id !== stage) finishStep(store, active.id);
      if (steps.find((step) => step.id === stage)?.state !== "active") {
        startStep(store, stage);
      }
    },
    onBundleDownload: downloadReporter(store, "files"),
    onCompose,
  };
}

/** Wait for GAIA to answer after the restart, then end on its address. */
async function finishRestart(
  store: CLIStore,
  repoPath: string,
  startedServices: number,
  headline: string,
): Promise<void> {
  const ports = readDockerComposePortOverrides(repoPath);
  const webPort = ports[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  const readiness = await waitForGaia(
    store,
    { apiUrl: localApiUrl("selfhost", ports), webPort },
    startedServices,
  );
  if (!readiness.ready) {
    store.setError(
      new Error(
        "GAIA restarted but didn't answer in time.\n'gaia status' shows which part is down; 'gaia logs' shows why.",
      ),
    );
    return;
  }
  setEnding(store, {
    lead: "Open:",
    target: installWebUrl(repoPath, webPort),
    also: [headline],
  });
}

async function runReleaseUpdate(
  store: CLIStore,
  repoPath: string,
  options: UpdateOptions,
): Promise<void> {
  const current = readPinnedGaiaVersion(repoPath);
  const target = options.version ?? GAIA_RELEASE_IMAGE_TAG;
  const explicit = options.version !== undefined;
  // Only a target that would be offered is worth a registry round trip.
  const worthChecking =
    explicit ||
    (releaseVersion(current) !== null && isNewerRelease(target, current));
  const gap = worthChecking
    ? await findReleaseImageGap(target, readConfig()?.bots ?? [])
    : null;
  const decision = decideReleaseUpdate({ current, target, explicit, gap });

  if (decision.kind === "development-build") {
    finishStep(
      store,
      CHECK_STEP.id,
      `GAIA runs a development build (${displayTag(current)})`,
    );
    setEnding(store, {
      lead: `To move it to the ${target} release:`,
      target: `gaia update --version ${target}`,
    });
    return;
  }
  if (decision.kind === "unavailable") {
    const { cause, next } = explainImageGap(decision.gap, "gaia up --build");
    // Asked-for releases fail; the release this CLI ships just isn't here yet.
    if (explicit) {
      fail(store, new Error(`${cause} Nothing was changed.\n${next}`));
      return;
    }
    finishStep(
      store,
      CHECK_STEP.id,
      `GAIA ${current} is the newest release here`,
    );
    store.updateData(UPDATE_NOTICE_KEY, cause);
    return;
  }
  const plan =
    decision.kind === "offer"
      ? await planReleaseUpdate(repoPath, target)
      : null;
  if (!plan || isReleaseCurrent(plan)) {
    finishStep(store, CHECK_STEP.id, `GAIA ${current} is up to date`);
    setEnding(store, newerReleaseEnding(CLI_VERSION));
    return;
  }
  finishStep(store, CHECK_STEP.id, `Found GAIA ${target}`);
  const offer: UpdateOffer = {
    question: offerHeadline(
      plan,
      decision.kind === "offer" && decision.downgrade,
    ),
    lines: [
      ...(await highlightsOf(target)),
      `What's new: ${RELEASE_NOTES_URL}`,
    ],
  };
  if (!(await confirmed(store, options, offer))) return;

  const startedServices = await applyReleaseUpdate(plan, stepReporter(store));
  await finishRestart(
    store,
    repoPath,
    startedServices,
    `GAIA is on ${target}; your data and settings were kept.`,
  );
}

async function runGitUpdate(
  store: CLIStore,
  repoPath: string,
  options: UpdateOptions,
): Promise<void> {
  const changes = await planGitUpdate(repoPath);
  if (changes.commits.length === 0) {
    finishStep(store, CHECK_STEP.id, "Already up to date with the branch");
    return;
  }
  const count = changes.commits.length;
  finishStep(
    store,
    CHECK_STEP.id,
    `Found ${count} new commit${count === 1 ? "" : "s"}`,
  );
  const shown = options.verbose
    ? changes.commits
    : changes.commits.slice(0, MAX_LISTED_COMMITS);
  const hidden = count - shown.length;
  const offer: UpdateOffer = {
    question: "Pull them, rebuild GAIA from source and restart?",
    lines: [
      ...shown,
      ...(hidden > 0 ? [`and ${hidden} more (--verbose lists them)`] : []),
      "Rebuilding is slow on small machines.",
    ],
  };
  if (!(await confirmed(store, options, offer))) return;

  const startedServices = await applyGitUpdate(repoPath, stepReporter(store));
  await finishRestart(
    store,
    repoPath,
    startedServices,
    "Updated and restarted from source.",
  );
}

async function runUpdateFlow(
  store: CLIStore,
  options: UpdateOptions,
): Promise<void> {
  initSteps(store, [
    CHECK_STEP,
    ...(options.git
      ? [
          {
            id: "pull",
            label: "Pulling the new commits",
            doneLabel: "Pulled the new commits",
          },
          imagesStep(true),
        ]
      : [
          {
            id: "files",
            label: "Getting the setup files",
            doneLabel: "Got the setup files",
            minor: true,
          },
          imagesStep(false),
          {
            id: "swap",
            label: "Switching to the new setup files",
            doneLabel: "Switched to the new setup files",
            minor: true,
          },
        ]),
    START_STEP,
  ]);
  startStep(store, CHECK_STEP.id);
  const repoPath = findInstallRoot();
  if (!repoPath) {
    fail(
      store,
      new Error(
        "GAIA isn't installed here, so there is nothing to update.\nInstall it with 'gaia up'.",
      ),
    );
    return;
  }
  if (options.git && options.version) {
    fail(
      store,
      new Error(
        "--version and --git can't be used together.\n--version moves to a published release; --git builds from source. Pick one.",
      ),
    );
    return;
  }
  try {
    await (options.git
      ? runGitUpdate(store, repoPath, options)
      : runReleaseUpdate(store, repoPath, options));
  } catch (e) {
    fail(
      store,
      new Error(
        `GAIA wasn't updated: ${(e as Error).message}\nYour data is untouched. Fix the cause above, then run 'gaia update' again.`,
      ),
    );
  }
}

export async function runUpdate(options: UpdateOptions = {}): Promise<void> {
  await runCommandUI({
    command: "update",
    whenNonInteractive: "plain",
    runFlow: (store) => runUpdateFlow(store, options),
    cancelHint: "Your data is untouched. Run 'gaia update' again to finish.",
  });
}
