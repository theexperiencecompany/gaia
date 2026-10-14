import { type RefObject, useCallback } from "react";

/** Shows the actions row on hover/focus by toggling its inline styles, and
 *  does nothing while actions are disabled (onboarding, read-only bubbles). */
export function useActionsHover(
  actionsRef: RefObject<HTMLDivElement | null>,
  disableActions: boolean,
) {
  const setVisible = useCallback(
    (visible: boolean) => {
      const el = actionsRef.current;
      if (!el || disableActions) return;
      el.style.opacity = visible ? "1" : "0";
      el.style.visibility = visible ? "visible" : "hidden";
    },
    [actionsRef, disableActions],
  );
  const handleMouseOver = useCallback(() => setVisible(true), [setVisible]);
  const handleMouseOut = useCallback(() => setVisible(false), [setVisible]);
  return { handleMouseOver, handleMouseOut };
}
