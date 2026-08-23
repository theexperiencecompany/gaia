// Imported statically rather than require()d at runtime: esbuild inlines the
// value at build time, so the version resolves identically whether the CLI
// runs from source (tsx) or from the bundled dist/index.js.
import packageJson from "../../package.json" with { type: "json" };

export const CLI_VERSION: string = packageJson.version;
