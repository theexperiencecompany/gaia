import { useTriggerAction } from "@openuidev/react-lang";

const NOOP = () => {};

/**
 * `useTriggerAction` from @openuidev/react-lang throws when called outside a
 * `<Renderer />`. Components that need to support standalone rendering (e.g.
 * the OpenUI demo page) call this wrapper instead — it falls back to a no-op
 * when no Renderer context is mounted.
 *
 * Hook order is preserved: the underlying hook always invokes one `useContext`
 * call before deciding whether to throw, so the try/catch only swallows the
 * thrown error, not a missed hook.
 */
export function useSafeTriggerAction(): ReturnType<typeof useTriggerAction> {
  try {
    // biome-ignore lint/correctness/useHookAtTopLevel: useTriggerAction internally calls exactly one useContext before deciding whether to throw, so the try/catch keeps hook order stable across renders.
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
