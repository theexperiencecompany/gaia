// ─── Shared animation helpers for demo components ─────────────────────────────

export const demoEase: [number, number, number, number] = [0.32, 0.72, 0, 1];
export const demoTx = { duration: 0.22, ease: demoEase };
export const demoSlideUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};
