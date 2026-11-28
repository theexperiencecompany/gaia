"use client";

import { TodosPage } from "@heygaia/effect-ui";
import { EffectRoot } from "@/components/effect/EffectRoot";

/** Client adapter: the page component is a function, so it must be imported
 * inside the client bundle rather than passed from a Server Component. */
export function EffectTodosPage({ apiBaseUrl }: { apiBaseUrl: string }) {
  return (
    <EffectRoot component={TodosPage} props={{}} apiBaseUrl={apiBaseUrl} />
  );
}
