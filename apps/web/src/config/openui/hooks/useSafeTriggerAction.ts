import { useTriggerAction } from "@openuidev/react-lang";

const NOOP = () => {
  /* fallback action handler used when no <Renderer /> context is mounted */
};

/**
 * `useTriggerAction` throws outside a `<Renderer />`; this wrapper falls
 * back to a no-op when no Renderer context is mounted (e.g. the OpenUI
 * demo page).
 *
 * `@openuidev/react-lang` doesn't export `OpenUIContext`, so we can't check
 * for a mounted Renderer ourselves — it calls exactly one `useContext`
 * before deciding, so hook order stays stable; the try/catch only swallows the thrown error.
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
