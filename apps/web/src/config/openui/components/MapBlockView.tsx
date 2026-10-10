import { Location01Icon } from "@icons";
import type { StyleSpecification } from "maplibre-gl";
import React from "react";
import type { z } from "zod";
import {
  MapArc,
  type MapArcDatum,
  MapGeoJSON,
  MapMarker,
  MapRoute,
  MapView,
  MarkerContent,
  MarkerLabel,
  MarkerPopup,
  MarkerTooltip,
} from "@/components/ui/map";
import { ToolCard } from "../primitives/ToolCard";
import { ToolInset } from "../primitives/ToolInset";
import type { mapBlockSchema } from "../promptSpecs";
import { MapAutoFit } from "./MapAutoFit";
import { MapBlockControls } from "./MapBlockControls";

// Basemap. maplibre's vector-tile Web Worker does not run in this app's runtime
// (vector basemaps never load — raster does), so use CARTO's RASTER dark
// basemap, which renders without the worker.
const CARTO_DARK_RASTER: StyleSpecification = {
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
        "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors © CARTO",
    },
  },
  layers: [{ id: "carto", type: "raster", source: "carto" }],
};

const MAP_STYLES = { dark: CARTO_DARK_RASTER, light: CARTO_DARK_RASTER };

export function MapBlockView(props: z.infer<typeof mapBlockSchema>) {
  const { markers, routes, arcs, blank, geojson } = props;
  // Center is optional — default to a whole-world view (handy for `geojson`
  // country/region maps that don't focus on one spot).
  const lat = props.lat ?? 20;
  const lng = props.lng ?? 0;
  const zoom = props.zoom ?? (blank || geojson ? 1.4 : 14);

  const hasExtras =
    (markers?.length ?? 0) > 0 ||
    (routes?.length ?? 0) > 0 ||
    (arcs?.length ?? 0) > 0;

  const allPoints = React.useMemo<[number, number][]>(() => {
    const pts: [number, number][] = [[lng, lat]];
    for (const mk of markers ?? []) pts.push([mk.lng, mk.lat]);
    for (const rt of routes ?? []) {
      for (const p of rt.points) pts.push([p.lng, p.lat]);
    }
    for (const a of arcs ?? []) {
      pts.push([a.from.lng, a.from.lat]);
      pts.push([a.to.lng, a.to.lat]);
    }
    return pts;
  }, [lat, lng, markers, routes, arcs]);

  const arcData = React.useMemo<MapArcDatum[]>(
    () =>
      (arcs ?? []).map((a, i) => ({
        id: a.id ?? `arc-${i}`,
        from: [a.from.lng, a.from.lat],
        to: [a.to.lng, a.to.lat],
      })),
    [arcs],
  );

  // Auto-fit to all markers/routes/arcs whenever there are any, so every point
  // is visible (re-fits on prop change). Pass fitBounds:false to keep an
  // explicit center/zoom.
  const fitBounds = props.fitBounds ?? hasExtras;

  const title = props.label ? (
    <span className="flex items-center gap-2">
      <Location01Icon className="size-4 text-primary" />
      {props.label}
    </span>
  ) : undefined;
  const subtitle =
    props.lat != null ? `${lat.toFixed(4)}, ${lng.toFixed(4)}` : undefined;

  return (
    <ToolCard size="standard" title={title} subtitle={subtitle}>
      <ToolInset flush>
        <MapView
          theme="dark"
          styles={MAP_STYLES}
          blank={blank}
          viewport={{ center: [lng, lat], zoom }}
          className="h-[220px] w-full overflow-hidden"
          attributionControl={false}
        >
          {geojson && <MapGeoJSON data={geojson} />}
          {!hasExtras && !blank && !geojson && (
            <MapMarker longitude={lng} latitude={lat}>
              <MarkerContent />
            </MapMarker>
          )}
          {markers?.map((mk) => (
            <MapMarker
              key={JSON.stringify(mk)}
              longitude={mk.lng}
              latitude={mk.lat}
            >
              <MarkerContent>
                <div className="relative h-3.5 w-3.5 rounded-full border-2 border-white bg-primary shadow-lg" />
                {mk.label && (
                  <MarkerLabel className="text-zinc-100 bg-zinc-800/80 backdrop-blur-sm rounded px-1.5 py-0.5">
                    {mk.label}
                  </MarkerLabel>
                )}
              </MarkerContent>
              {mk.tooltip && <MarkerTooltip>{mk.tooltip}</MarkerTooltip>}
              {mk.popup && <MarkerPopup>{mk.popup}</MarkerPopup>}
            </MapMarker>
          ))}
          {routes?.map((rt) => (
            <MapRoute
              key={JSON.stringify(rt)}
              coordinates={rt.points.map((p) => [p.lng, p.lat])}
              color={rt.color ?? "#3b82f6"}
              width={rt.width ?? 3}
              opacity={rt.opacity ?? 0.85}
              dashArray={rt.dashArray}
            />
          ))}
          {arcData.length > 0 && <MapArc data={arcData} />}
          <MapAutoFit points={allPoints} enabled={fitBounds} />
          <MapBlockControls initialCenter={[lng, lat]} initialZoom={zoom} />
        </MapView>
      </ToolInset>
    </ToolCard>
  );
}
