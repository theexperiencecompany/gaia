import { useEffect } from "react";

import { useMap } from "@/components/ui/map";

// Dark Matter draws land (its background) and water near-black, so the globe read as
// a blur; land a step lighter than the ocean keeps the continents legible at night.
const LAND_COLOR = "#3f3f46"; // zinc-700
const OCEAN_COLOR = "#18181b"; // zinc-900
const BACKGROUND_LAYER_ID = "background";
const WATER_LAYER_ID = "water";

/** Strip the enclosing MapView's basemap to its land and ocean, lit for a dark globe. */
export function useNightGlobeBasemap() {
  const { map, isLoaded } = useMap();

  useEffect(() => {
    if (!map || !isLoaded) return;
    for (const layer of map.getStyle().layers) {
      if (layer.type === "symbol") {
        map.setLayoutProperty(layer.id, "visibility", "none");
      }
    }
    map.setPaintProperty(BACKGROUND_LAYER_ID, "background-color", LAND_COLOR);
    map.setPaintProperty(WATER_LAYER_ID, "fill-color", OCEAN_COLOR);
  }, [map, isLoaded]);
}
