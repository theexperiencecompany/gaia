/** The prerequisites the CLI can install, by their System Checks row. */
export type InstallablePrerequisite = "git" | "docker";

/** The stages a Docker install goes through, in order. */
export type InstallStage =
  | "prepare"
  | "download"
  | "install"
  | "start"
  | "check";

/** Where an install is: its stage, and a short note on how far ("84 / 112 MB", "containerd.io"). */
export interface InstallProgress {
  stage: InstallStage;
  note?: string;
}

/** Where Docker's install script is, read from the commands it traces. */
export type DockerInstallStage =
  | { stage: "preparing"; detail: string }
  | { stage: "downloading"; packages: string[] }
  | { stage: "starting" };
