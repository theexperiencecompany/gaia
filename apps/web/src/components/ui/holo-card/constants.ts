// Image paths used across HoloCard components
export const CARD_IMAGES = {
  LOGO_WHITE: "/images/logos/text_w_logo_white.webp",
  EXPERIENCE_LOGO: "/images/logos/experience_logo.svg",
} as const;

// Logo dimensions
export const LOGO_SIZES = {
  FRONT: {
    width: 100,
    height: 30,
  },
  BACK: {
    width: 80,
    height: 24,
  },
  EXPERIENCE: {
    width: 30,
    height: 30,
  },
} as const;

// Position calculation constants
export const POSITION_CALC = {
  DAMPING_FACTOR: 1.5, // Used to dampen the background position offset
} as const;

// Common CSS class patterns
export const CARD_CLASSES = {
  OVERLAY: "pointer-events-none absolute inset-0 z-3",
  CONTENT_WRAPPER:
    "pointer-events-none absolute z-2 flex h-full w-full flex-col items-start justify-end p-3 text-white transition",
  CONTENT_WRAPPER_BACK:
    "pointer-events-none absolute z-2 flex h-full w-full flex-col items-start justify-between p-3 text-white",
  LOGO_BADGE:
    "rounded-full bg-white/30 p-1 px-2 font-serif text-xl font-light text-white/70 backdrop-blur-md",
  HOUSE_BADGE:
    "rounded-full bg-white/20 p-1 px-4 font-serif text-xl font-light text-white/70 backdrop-blur-md",
  HOUSE_BADGE_BACK:
    "rounded-full bg-white/20 p-1 px-3 font-serif text-xl font-light text-white/70 backdrop-blur-md",
  INFO_BOX:
    "relative flex w-full flex-col gap-1 overflow-hidden rounded-2xl bg-black/20 p-3 backdrop-blur-md",
  INFO_BOX_BACK:
    "relative overflow-hidden rounded-2xl bg-black/20 p-4 backdrop-blur-md",
  FOOTER_BOX:
    "flex w-full items-center justify-between rounded-xl bg-black/20 p-3 backdrop-blur-md",
  EXPERIENCE_LOGO: "scale-125 opacity-10",
} as const;
