import { useTriggerAction } from "@openuidev/react-lang";

const NOOP = () => {
  /* fallback action handler used when no <Renderer /> context is mounted */
};

/**
 * `useTriggerAction` from @openuidev/react-lang throws when called outside a
 * `<Renderer />`. Components that need to support standalone rendering (e.g.
 * the OpenUI demo page) call this wrapper instead — it falls back to a no-op
 * when no Renderer context is mounted.
 *
 * `@openuidev/react-lang` does not export `OpenUIContext`, so we cannot read
 * the context ourselves to check for a mounted <Renderer /> before calling the
 * hook. `useTriggerAction` internally calls exactly one `useContext` before
 * deciding whether to throw, so hook order is stable across renders — the
 * try/catch only swallows the thrown error, never a hook call.
 */
export function useSafeTriggerAction(): ReturnType<typeof useTriggerAction> {
  try {
    // biome-ignore lint/correctness/useHookAtTopLevel: @openuidev/react-lang throws outside <Renderer /> and does not export OpenUIContext; see doc comment above
    const trigger = useTriggerAction();
    return trigger;
  } catch (err) {
    // Only swallow the "hook used outside <Renderer />" error. Anything else
    // (changed API, internal assertion, app-level bug) should surface instead
    // of silently degrading every Button / action handler to a no-op.
    if (!(err instanceof Error) || !/Renderer/i.test(err.message)) throw err;
    return NOOP;
  }
}
