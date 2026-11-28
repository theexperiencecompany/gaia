"use client";

import dynamic from "next/dynamic";

/** Loads the Effect UI chunk only when the ?effect=1 branch renders. */
const EffectTodosPage = dynamic(
  () =>
    import("./pages/EffectTodosPage").then((module) => module.EffectTodosPage),
  { ssr: false, loading: () => null },
);

export function EffectTodosBranch({ apiBaseUrl }: { apiBaseUrl: string }) {
  return <EffectTodosPage apiBaseUrl={apiBaseUrl} />;
}
