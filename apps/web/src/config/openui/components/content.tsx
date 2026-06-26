import { Button } from "@heroui/react";
import {
  Location01Icon,
  MinusSignIcon,
  PlusSignIcon,
  RefreshIcon,
} from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import type { StyleSpecification } from "maplibre-gl";
import * as m from "motion/react-m";
import { useParams } from "next/navigation";
import React from "react";
import type { z } from "zod";
import {
  MapArc,
  type MapArcDatum,
  MapGeoJSON,
  MapMarker,
  MapRoute,
  Map as MapView,
  MarkerContent,
  MarkerLabel,
  MarkerPopup,
  MarkerTooltip,
  useMap,
} from "@/components/ui/map";
import { NumberTicker } from "@/components/ui/number-ticker";
import { resolveArtifactSrc } from "@/features/chat/api/sessionFilesApi";
import { ToolCard, ToolInset } from "../primitives";
import {
  audioPlayerSchema,
  imageGallerySchema,
  mapBlockSchema,
  numberTickerSchema,
  videoBlockSchema,
} from "../promptSpecs";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function GalleryImage({
  img,
  aspectRatio = "3/2",
}: {
  img: { src: string; alt?: string; caption?: string };
  aspectRatio?: string;
}) {
  const params = useParams<{ id?: string }>();
  const src = resolveArtifactSrc(img.src, params?.id) ?? img.src;
  return (
    <m.div
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="relative overflow-hidden rounded-xl cursor-pointer"
      style={{ aspectRatio }}
    >
      {/* biome-ignore lint/performance/noImgElement: external user-provided URLs */}
      <img
        src={src}
        alt={img.alt ?? ""}
        className="w-full h-full object-cover"
      />
      {img.caption && (
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-3 py-2 pointer-events-none">
          <p className="text-xs text-white/90 font-medium leading-snug">
            {img.caption}
          </p>
        </div>
      )}
    </m.div>
  );
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

const GALLERY_COLS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  3: "grid-cols-3",
  4: "grid-cols-4",
  5: "grid-cols-5",
  6: "grid-cols-6",
};

function defaultGalleryCols(n: number): number {
  if (n <= 1) return 1;
  if (n === 2) return 2;
  if (n === 3) return 3;
  return 2;
}

const GALLERY_GAP: Record<
  NonNullable<z.infer<typeof imageGallerySchema>["gap"]>,
  string
> = {
  xs: "gap-1",
  sm: "gap-2",
  md: "gap-3",
  lg: "gap-5",
};

const GALLERY_MAX_W: Record<
  NonNullable<z.infer<typeof imageGallerySchema>["maxWidth"]>,
  string
> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
  full: "max-w-full",
};

export function ImageGalleryView(props: z.infer<typeof imageGallerySchema>) {
  const images = props.images;
  const aspectRatio = props.aspectRatio ?? "3/2";
  const cols = props.columns ?? defaultGalleryCols(images.length);
  const gridCols = GALLERY_COLS[cols] ?? "grid-cols-2";
  const gap = GALLERY_GAP[props.gap ?? "md"];
  const maxW = GALLERY_MAX_W[props.maxWidth ?? "xl"];

  return (
    <div className={`grid ${gridCols} ${gap} w-full ${maxW}`}>
      {images.map((img) => (
        <GalleryImage key={img.src} img={img} aspectRatio={aspectRatio} />
      ))}
    </div>
  );
}

export function VideoBlockView(props: z.infer<typeof videoBlockSchema>) {
  const src = props.src;
  const isYouTube = src.includes("youtube.com") || src.includes("youtu.be");
  const isVimeo = src.includes("vimeo.com");

  let embedSrc = src;
  if (isYouTube) {
    const match =
      src.match(/[?&]v=([^&]+)/) ??
      src.match(/youtu\.be\/([^?]+)/) ??
      src.match(/embed\/([^?]+)/);
    const videoId = match?.[1];
    if (videoId) embedSrc = `https://www.youtube.com/embed/${videoId}`;
  } else if (isVimeo) {
    const match = src.match(/vimeo\.com\/(\d+)/);
    const videoId = match?.[1];
    if (videoId) embedSrc = `https://player.vimeo.com/video/${videoId}`;
  }

  const isEmbed = isYouTube || isVimeo;

  return isEmbed ? (
    <iframe
      src={embedSrc}
      className="w-full max-w-2xl rounded-2xl aspect-video"
      style={{ border: "none" }}
      allowFullScreen
      title={props.title ?? "video"}
    />
  ) : (
    <video
      src={src}
      poster={props.poster}
      controls
      className="w-full max-w-2xl rounded-2xl aspect-video object-cover"
    >
      <track kind="captions" />
    </video>
  );
}

export function AudioPlayerView(props: z.infer<typeof audioPlayerSchema>) {
  return (
    <ToolCard size="compact" title={props.title} subtitle={props.description}>
      <audio src={props.src} controls className="w-full">
        <track kind="captions" />
      </audio>
    </ToolCard>
  );
}

function MapBlockControls({
  initialCenter,
  initialZoom,
}: {
  initialCenter: [number, number];
  initialZoom: number;
}) {
  const { map } = useMap();

  const handleZoomIn = () => {
    map?.zoomTo(map.getZoom() + 1, { duration: 250 });
  };
  const handleZoomOut = () => {
    map?.zoomTo(map.getZoom() - 1, { duration: 250 });
  };
  const handleReset = () => {
    map?.flyTo({
      center: initialCenter,
      zoom: initialZoom,
      bearing: 0,
      pitch: 0,
      duration: 400,
    });
  };

  return (
    <div className="absolute top-2 right-2 z-10 flex flex-col gap-1">
      <Button
        isIconOnly
        size="sm"
        variant="flat"
        radius="lg"
        onPress={handleZoomIn}
        aria-label="Zoom in"
        className="bg-zinc-800/90 text-zinc-200 backdrop-blur-md data-[hover=true]:bg-zinc-700"
      >
        <PlusSignIcon className="size-3.5" />
      </Button>
      <Button
        isIconOnly
        size="sm"
        variant="flat"
        radius="lg"
        onPress={handleZoomOut}
        aria-label="Zoom out"
        className="bg-zinc-800/90 text-zinc-200 backdrop-blur-md data-[hover=true]:bg-zinc-700"
      >
        <MinusSignIcon className="size-3.5" />
      </Button>
      <Button
        isIconOnly
        size="sm"
        variant="flat"
        radius="lg"
        onPress={handleReset}
        aria-label="Reset view"
        className="bg-zinc-800/90 text-zinc-200 backdrop-blur-md data-[hover=true]:bg-zinc-700"
      >
        <RefreshIcon className="size-3.5" />
      </Button>
    </div>
  );
}

function MapAutoFit({
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
          {markers?.map((mk, i) => (
            <MapMarker
              // biome-ignore lint/suspicious/noArrayIndexKey: marker list has no stable id
              key={`marker-${i}`}
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
          {routes?.map((rt, i) => (
            <MapRoute
              // biome-ignore lint/suspicious/noArrayIndexKey: route list has no stable id
              key={`route-${i}`}
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

const NUMBER_TICKER_SIZE: Record<
  string,
  { container: string; value: string; unit: string }
> = {
  sm: { container: "p-3 min-w-[120px]", value: "text-2xl", unit: "text-xs" },
  md: { container: "p-4 min-w-[160px]", value: "text-3xl", unit: "text-sm" },
  lg: { container: "p-5 min-w-[200px]", value: "text-4xl", unit: "text-base" },
};

export function NumberTickerView(props: z.infer<typeof numberTickerSchema>) {
  const isDecimal = props.value % 1 !== 0;
  const sz = NUMBER_TICKER_SIZE[props.size ?? "md"];
  return (
    <div
      className={`rounded-2xl bg-zinc-800 text-center w-fit ${sz.container}`}
    >
      {props.label && (
        <p className="text-xs text-zinc-500 mb-2">{props.label}</p>
      )}
      <div className="flex items-end justify-center gap-1">
        <span className={`${sz.value} font-semibold text-zinc-100`}>
          <NumberTicker value={props.value} decimalPlaces={isDecimal ? 1 : 0} />
        </span>
        {props.unit && (
          <span className={`${sz.unit} text-zinc-500 mb-0.5`}>
            {props.unit}
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

export const imageGalleryDef = defineComponent({
  name: "ImageGallery",
  description: "Grid of images with captions.",
  props: imageGallerySchema,
  component: ({ props }) => React.createElement(ImageGalleryView, props),
});

export const videoBlockDef = defineComponent({
  name: "VideoBlock",
  description: "YouTube/Vimeo embed or native video player.",
  props: videoBlockSchema,
  component: ({ props }) => React.createElement(VideoBlockView, props),
});

export const audioPlayerDef = defineComponent({
  name: "AudioPlayer",
  description: "Audio player with title and description.",
  props: audioPlayerSchema,
  component: ({ props }) => React.createElement(AudioPlayerView, props),
});

export const mapBlockDef = defineComponent({
  name: "MapBlock",
  description: "OpenStreetMap embed for a lat/lng location.",
  props: mapBlockSchema,
  component: ({ props }) => React.createElement(MapBlockView, props),
});

export const numberTickerDef = defineComponent({
  name: "NumberTicker",
  description: "Animated count-up number display.",
  props: numberTickerSchema,
  component: ({ props }) => React.createElement(NumberTickerView, props),
});
