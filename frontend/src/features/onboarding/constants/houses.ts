import { House } from "@/features/onboarding/hooks/useOnboardingWebSocket";

export const HOUSES: Record<House, { image: string }> = {
  frostpeak: {
    image:
      "https://i.pinimg.com/1200x/bf/1a/99/bf1a99c4c2cd8f378b9e4493f71e7e64.jpg",
  },
  greenvale: {
    image:
      "https://i.pinimg.com/1200x/3b/3e/11/3b3e1167fcfb0933070b6064ce9c72cd.jpg",
  },
  mistgrove: { image: "/images/wallpapers/holo/mistgrove.png" },
  bluehaven: {
    image:
      "https://i.pinimg.com/1200x/27/0a/74/270a74bdc412f9eeae4d2403ebc9bd63.jpg",
  },
};

/**
 * Safely get house image URL with proper type checking
 * Always returns a valid image URL
 */
export function getHouseImage(house: string | undefined | null): string {
  if (!house) {
    return HOUSES.bluehaven.image;
  }

  const normalizedHouse = house.toLowerCase() as House;

  if (normalizedHouse in HOUSES) {
    return HOUSES[normalizedHouse].image;
  }

  return HOUSES.bluehaven.image;
}

/**
 * Safely normalize house name to valid House type
 */
export function normalizeHouse(house: string | undefined | null): House {
  if (!house) {
    return "bluehaven";
  }

  const normalizedHouse = house.toLowerCase() as House;

  if (normalizedHouse in HOUSES) {
    return normalizedHouse;
  }

  return "bluehaven";
}
