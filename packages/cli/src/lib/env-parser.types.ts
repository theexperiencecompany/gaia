export type SetupMode = "selfhost" | "developer";

export interface EnvVar {
  name: string;
  required: boolean;
  category: string;
  description: string;
  affectedFeatures: string;
  defaultValue?: string;
  docsUrl?: string;
}

export interface EnvCategory {
  name: string;
  description: string;
  affectedFeatures: string;
  requiredInProd: boolean;
  allRequired: boolean;
  docsUrl?: string;
  alternativeGroup?: string;
  /** False for a group a self-hosted instance does not use; self-host setup skips it. */
  selfhostSetup: boolean;
  variables: EnvVar[];
}

export interface WebEnvVar {
  name: string;
  value: string;
  category: string;
}
