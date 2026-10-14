// Imported statically rather than require()d at runtime: esbuild inlines the
// value at build time, so the version resolves identically whether the CLI
// runs from source (tsx) or from the bundled dist/index.js.
import packageJson from "../../package.json" with { type: "json" };

export const CLI_VERSION: string = packageJson.version;

/**
 * The GAIA image tag this CLI release installs. publish-cli.yml tags the
 * gaia and gaia-web images that were live at publish time with it, so every
 * CLI release pins one tested image pair.
 */
export const GAIA_RELEASE_IMAGE_TAG = `v${CLI_VERSION}`;
