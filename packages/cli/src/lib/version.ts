// Imported statically rather than require()d at runtime: esbuild inlines the
// value at build time, so the version resolves identically whether the CLI
// runs from source (tsx) or from the bundled dist/index.js.
import packageJson from "../../package.json" with { type: "json" };
import { GAIA_VERSION_ENV_KEY } from "./env-writer.js";

export const CLI_VERSION: string = packageJson.version;

/**
 * The GAIA release a CLI installs: its own (publish-cli.yml tags the gaia and
 * gaia-web images live at publish time with it, so every CLI release pins one
 * tested image pair), unless GAIA_VERSION names another, as compose itself
 * would follow it.
 */
export function releaseImageTag(
  env: NodeJS.ProcessEnv,
  cliVersion: string,
): string {
  return env[GAIA_VERSION_ENV_KEY] || `v${cliVersion}`;
}

export const GAIA_RELEASE_IMAGE_TAG = releaseImageTag(process.env, CLI_VERSION);
