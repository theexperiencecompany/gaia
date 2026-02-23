import { createRequire } from "module";

const require = createRequire(import.meta.url);

export const CLI_VERSION = (
  require("../../package.json") as { version?: string }
).version || "0.0.0";
