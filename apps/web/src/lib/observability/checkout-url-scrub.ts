import type { BeforeSendFn, CaptureResult, Properties } from "posthog-js";

import { DODO_RETURN_PARAM } from "@/features/pricing/lib/dodoReturnUrl";

/** Params that mark a URL as a Dodo return; `status` alone is too common a name. */
const DODO_RETURN_MARKERS: readonly string[] = [
  DODO_RETURN_PARAM.subscriptionId,
  DODO_RETURN_PARAM.paymentId,
  DODO_RETURN_PARAM.email,
];

/** The value with Dodo's return params removed when it is a Dodo return URL; anything else as is. */
function withoutReturnParams(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const url = URL.parse(value);
  if (!url || !DODO_RETURN_MARKERS.some((param) => url.searchParams.has(param)))
    return value;
  for (const param of Object.values(DODO_RETURN_PARAM))
    url.searchParams.delete(param);
  return url.toString();
}

function scrubbed(properties: Properties): Properties {
  return Object.fromEntries(
    Object.entries(properties).map(([key, value]) => [
      key,
      withoutReturnParams(value),
    ]),
  );
}

/**
 * PostHog `before_send` hook: takes Dodo's return params out of every URL an
 * event carries (`$current_url`, `$referrer`, the `$initial_*` person
 * properties), so a load that lands on a return URL never ships the
 * customer's email, whichever runs first on the page.
 */
export const scrubCheckoutReturnParams: BeforeSendFn = (result) => {
  if (!result) return result;
  const clean: CaptureResult = {
    ...result,
    properties: scrubbed(result.properties),
  };
  if (result.$set) clean.$set = scrubbed(result.$set);
  if (result.$set_once) clean.$set_once = scrubbed(result.$set_once);
  return clean;
};
