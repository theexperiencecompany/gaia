export type ResourceLevel = "ok" | "warn" | "fail";

export interface ResourceVerdict {
  level: ResourceLevel;
  detail: string;
  fix?: string;
}

/** A fresh install still has to download the images; a running one only grows its data. */
export type DiskPurpose = "install" | "run";

/** Where Docker runs, for the memory fix: a Mac's VM, WSL's VM, or the machine itself. */
export interface MemoryHost {
  platform: NodeJS.Platform;
  wsl: boolean;
}
