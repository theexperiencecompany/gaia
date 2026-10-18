import type { ComposePhase } from "../../lib/compose-progress.types.js";
import type { DownloadProgress } from "../../lib/download.js";
import type { ReleaseImageGap } from "../../lib/image-availability.js";

/** What changed between two git refs, limited to {@link WATCH_PATHS}. */
export interface ChangeSummary {
  commits: string[];
}

/** What `gaia update` does about a release, decided before anything changes. */
export type ReleaseDecision =
  /** The install runs a non-release build (latest, a commit) and no --version named one. */
  | { kind: "development-build" }
  /** The target is not newer than what runs, and no --version asked for it. */
  | { kind: "up-to-date" }
  /** The target's images are missing for this computer. */
  | { kind: "unavailable"; gap: ReleaseImageGap }
  | { kind: "offer"; downgrade: boolean };

/** What the install is on disk, and the files it owns that an update replaces. */
export type InstallLayout =
  /** A release's setup files; the manifest names them. */
  | { kind: "bundle"; version: string; files: string[] }
  /** A git checkout `gaia up` cloned; the update moves it to release files. */
  | { kind: "checkout"; files: string[] };

/** Where a release-mode update moves the install from and to. */
export interface ReleasePlan {
  repoPath: string;
  fromVersion: string;
  toVersion: string;
  layout: InstallLayout;
}

/** What a release-mode update tells its caller as it goes. */
export interface ReleaseUpdateReporter {
  onStatus: (message: string) => void;
  onBundleDownload: (progress: DownloadProgress) => void;
  onImagePull: (phase: ComposePhase) => void;
}
