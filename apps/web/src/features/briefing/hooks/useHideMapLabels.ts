import { useEffect } from "react";

import { useMap } from "@/components/ui/map";

/** Hide every text and icon layer of the enclosing MapView's basemap, leaving only the land. */
export function useHideMapLabels() {
  const { map, isLoaded } = useMap();

  useEffect(() => {
    if (!map || !isLoaded) return;
    for (const layer of map.getStyle().layers) {
      if (layer.type === "symbol") {
        map.setLayoutProperty(layer.id, "visibility", "none");
      }
    }
  }, [map, isLoaded]);
}
