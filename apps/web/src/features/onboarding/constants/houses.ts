import type { House } from "@/features/onboarding/types/websocket";

export const HOUSES: Record<House, { image: string }> = {
  frostpeak: { image: "/images/wallpapers/holo/frostpeak.jpg" },
  greenvale: { image: "/images/wallpapers/holo/greenvale.jpg" },
  mistgrove: { image: "/images/wallpapers/holo/mistgrove.png" },
  bluehaven: { image: "/images/wallpapers/holo/bluehaven.jpg" },
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
