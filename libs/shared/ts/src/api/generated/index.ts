/**
 * The API's request/response types, generated from `apps/api/openapi.json`
 * by `mise api:types`. Every component schema is exported under the API's
 * own name — `import type { TodoResponse } from "@gaia/shared/api/generated"`.
 * Never hand-write a type that mirrors a Pydantic model; the hygiene lane
 * `checks.mjs api-schema-types` fails a hand-written twin.
 */
export type * from "./schema";
