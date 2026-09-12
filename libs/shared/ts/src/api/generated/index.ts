/**
 * The API's request/response types, generated from `apps/api/openapi.json`
 * by `mise api:types`. Never hand-write a type that mirrors a Pydantic model;
 * pick it up here with `Schema<"ModelName">` (the hygiene lane
 * `checks.mjs api-schema-types` fails a hand-written twin).
 */
import type { components, operations, paths } from "./schema";

export type { components, operations, paths };

/** A named component schema, e.g. `Schema<"TodoResponse">`. */
export type Schema<Name extends keyof components["schemas"]> =
  components["schemas"][Name];

/**
 * Body of every non-2xx response (`ErrorEnvelope` in the API). Named
 * `ApiErrorBody` because `@gaia/shared/api` already exports the `ApiError`
 * class the bots throw.
 */
export type ApiErrorBody = Schema<"ErrorEnvelope">;
