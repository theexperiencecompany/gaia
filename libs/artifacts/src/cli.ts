/**
 * Validate one artifact program: reads {"program", "brief", "interactive"} as JSON on stdin and writes the
 * ValidationResult as JSON on stdout. The API (apps/api/app/services/openui_artifacts/validate.py) runs it.
 */
import { readFileSync } from "node:fs";
import { z } from "zod";
import { validateArtifact } from "./validate";

const request = z.object({
  program: z.string(),
  brief: z.string(),
  interactive: z.boolean(),
});

const { program, brief, interactive } = request.parse(
  JSON.parse(readFileSync(0, "utf8")),
);
process.stdout.write(
  JSON.stringify(validateArtifact(program, brief, { interactive })),
);
