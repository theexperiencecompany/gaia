import React from "react";
import { useMap } from "@/components/ui/map";

export function MapAutoFit({
  points,
  enabled,
}: {
  points: [number, number][];
  enabled: boolean;
}) {
  const { map, isLoaded } = useMap();

  React.useEffect(() => {
    if (!enabled || !isLoaded || !map || points.length < 2) return;
    let minLng = points[0][0];
    let maxLng = points[0][0];
    let minLat = points[0][1];
    let maxLat = points[0][1];
    for (const [lng, lat] of points) {
      if (lng < minLng) minLng = lng;
      if (lng > maxLng) maxLng = lng;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
    map.fitBounds(
      [
        [minLng, minLat],
        [maxLng, maxLat],
      ],
      { padding: 40, duration: 400, maxZoom: 14 },
    );
  }, [map, isLoaded, enabled, points]);

  return null;
}
