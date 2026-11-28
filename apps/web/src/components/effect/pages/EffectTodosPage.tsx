"use client";

import { TodosPage } from "@heygaia/effect-ui/pages/todos/TodosPage";
import { EffectRoot } from "@/components/effect/EffectRoot";

const TODOS_PROPS = {};

/** Client adapter: the page component is a function, so it must be imported
 * inside the client bundle rather than passed from a Server Component. */
export function EffectTodosPage({ apiBaseUrl }: { apiBaseUrl: string }) {
  return (
    <EffectRoot
      component={TodosPage}
      props={TODOS_PROPS}
      apiBaseUrl={apiBaseUrl}
    />
  );
}
