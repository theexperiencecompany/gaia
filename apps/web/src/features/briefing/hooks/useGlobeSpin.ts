import { useReducedMotion } from "motion/react";
import { useEffect } from "react";

import { useMap } from "@/components/ui/map";

/** Degrees of longitude the globe turns per second while idle. */
const SPIN_DEGREES_PER_SECOND = 3;

/**
 * Turn the enclosing MapView's globe slowly eastward. The spin holds while the
 * pointer is over the globe, so a hovered city stays put under its tooltip and a
 * drag is never fought, and it never starts for reduced-motion users.
 */
export function useGlobeSpin() {
  const { map, isLoaded } = useMap();
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!map || !isLoaded || reduceMotion) return;
    const container = map.getContainer();
    let held = false;
    let frame = 0;
    let last = performance.now();

    const tick = (now: number) => {
      if (!held && !map.isMoving()) {
        const center = map.getCenter();
        const step = (SPIN_DEGREES_PER_SECOND * (now - last)) / 1000;
        map.setCenter([center.lng + step, center.lat]);
      }
      last = now;
      frame = requestAnimationFrame(tick);
    };
    const hold = () => {
      held = true;
    };
    const release = () => {
      held = false;
    };

    container.addEventListener("pointerenter", hold);
    container.addEventListener("pointerleave", release);
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      container.removeEventListener("pointerenter", hold);
      container.removeEventListener("pointerleave", release);
    };
  }, [map, isLoaded, reduceMotion]);
}
