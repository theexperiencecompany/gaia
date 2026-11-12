/**
 * Validate one artifact program: reads {"program", "brief"} as JSON on stdin and writes the
 * ValidationResult as JSON on stdout. The API (app/services/artifacts/validate.py) runs it.
 */
import { readFileSync } from "node:fs";
import { z } from "zod";
import { validateArtifact } from "../../../apps/web/src/features/artifacts/openui/validate";

const request = z.object({ program: z.string(), brief: z.string() });

const { program, brief } = request.parse(JSON.parse(readFileSync(0, "utf8")));
process.stdout.write(JSON.stringify(validateArtifact(program, brief)));
