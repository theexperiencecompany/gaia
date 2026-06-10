import { Button, Chip } from "@heroui/react";
import {
  Location01Icon,
  MinusSignIcon,
  PlusSignIcon,
  RefreshIcon,
} from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import * as m from "motion/react-m";
import { useParams } from "next/navigation";
import React from "react";
import { z } from "zod";
import { ChevronLeft, ChevronRight } from "@/components/shared/icons";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
  useCarousel,
} from "@/components/ui/carousel";
import {
  MapArc,
  type MapArcDatum,
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
import { useSafeTriggerAction } from "../hooks/useSafeTriggerAction";
import { ToolCard, ToolInset } from "../primitives";

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

export const imageGallerySchema = z.object({
  images: z.array(
    z.object({
      src: z.string(),
      alt: z.string().optional(),
      caption: z.string().optional(),
    }),
  ),
  columns: z.number().int().min(1).max(6).optional(),
  gap: z.enum(["xs", "sm", "md", "lg"]).optional(),
  aspectRatio: z.string().optional(),
  maxWidth: z.enum(["sm", "md", "lg", "xl", "full"]).optional(),
});

export const videoBlockSchema = z.object({
  src: z.string(),
  title: z.string().optional(),
  poster: z.string().optional(),
});

export const audioPlayerSchema = z.object({
  src: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
});

const mapPointSchema = z.object({
  lat: z.number(),
  lng: z.number(),
});

const mapMarkerSchema = z.object({
  lat: z.number(),
  lng: z.number(),
  label: z.string().optional(),
  popup: z.string().optional(),
  tooltip: z.string().optional(),
});

const mapRouteItemSchema = z.object({
  points: z.array(mapPointSchema),
  color: z.string().optional(),
  width: z.number().optional(),
  opacity: z.number().optional(),
  dashArray: z.tuple([z.number(), z.number()]).optional(),
});

const mapArcItemSchema = z.object({
  id: z.union([z.string(), z.number()]).optional(),
  from: mapPointSchema,
  to: mapPointSchema,
  label: z.string().optional(),
});

export const mapBlockSchema = z.object({
  lat: z.number(),
  lng: z.number(),
  label: z.string().optional(),
  zoom: z.number().optional(),
  markers: z.array(mapMarkerSchema).optional(),
  routes: z.array(mapRouteItemSchema).optional(),
  arcs: z.array(mapArcItemSchema).optional(),
  fitBounds: z.boolean().optional(),
});

export const numberTickerSchema = z.object({
  value: z.number(),
  label: z.string().optional(),
  unit: z.string().optional(),
  duration: z.number().optional(),
  size: z.enum(["sm", "md", "lg"]).optional(),
});

export const carouselSchema = z.object({
  items: z.array(
    z.object({
      title: z.string(),
      body: z.string().optional(),
      image: z.string().optional(),
      badge: z.string().optional(),
      actions: z
        .array(z.object({ label: z.string(), value: z.string() }))
        .optional(),
    }),
  ),
  autoPlay: z.boolean().optional(),
});

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

function CarouselDotIndicators() {
  const { selectedIndex, scrollSnaps, scrollTo } = useCarousel();
  if (scrollSnaps.length <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-1.5">
      {scrollSnaps.map((_, index) => (
        <button
          // biome-ignore lint/suspicious/noArrayIndexKey: scroll snap dots have no stable identifier
          key={index}
          type="button"
          aria-label={`Go to slide ${index + 1}`}
          onClick={() => scrollTo(index)}
          className={[
            "rounded-full transition-all duration-200",
            index === selectedIndex
              ? "w-2 h-2 bg-zinc-300"
              : "w-1.5 h-1.5 bg-zinc-600 hover:bg-zinc-500",
          ].join(" ")}
        />
      ))}
    </div>
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

export function MapBlockView(props: z.infer<typeof mapBlockSchema>) {
  const { lat, lng, markers, routes, arcs } = props;
  const zoom = props.zoom ?? 14;

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

  const fitBounds = props.fitBounds ?? (hasExtras && props.zoom == null);

  const title = props.label ? (
    <span className="flex items-center gap-2">
      <Location01Icon className="size-4 text-primary" />
      {props.label}
    </span>
  ) : undefined;
  const subtitle = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;

  return (
    <ToolCard size="standard" title={title} subtitle={subtitle}>
      <ToolInset flush>
        <MapView
          theme="dark"
          viewport={{ center: [lng, lat], zoom }}
          className="h-[220px] w-full overflow-hidden"
          attributionControl={false}
        >
          {!hasExtras && (
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

export function CarouselView(props: z.infer<typeof carouselSchema>) {
  const handleAction = useSafeTriggerAction();

  const total = props.items.length;

  return (
    <ToolCard size="full" className="max-w-(--breakpoint-sm)!">
      <Carousel opts={{ align: "start", loop: true }}>
        <CarouselContent className="-ml-0">
          {props.items.map((item) => (
            <CarouselItem key={item.title} className="pl-0 h-full">
              <ToolInset className="min-h-full flex flex-col p-4">
                {item.image && (
                  <>
                    {/* biome-ignore lint/performance/noImgElement: external user-provided URLs */}
                    <img
                      src={item.image}
                      alt={item.title}
                      className="w-full rounded-2xl object-cover h-40 mb-3"
                    />
                  </>
                )}
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-semibold text-zinc-100">
                    {item.title}
                  </p>
                  {item.badge && (
                    <Chip
                      size="sm"
                      variant="flat"
                      className="shrink-0 text-xs text-zinc-400"
                    >
                      {item.badge}
                    </Chip>
                  )}
                </div>
                {item.body && (
                  <p className="text-xs text-zinc-400 mt-1 flex-1">
                    {item.body}
                  </p>
                )}
                {item.actions && item.actions.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-auto pt-3">
                    {item.actions.map((action) => (
                      <Button
                        key={action.value}
                        size="sm"
                        variant="flat"
                        onPress={() => handleAction(action.value)}
                      >
                        {action.label}
                      </Button>
                    ))}
                  </div>
                )}
              </ToolInset>
            </CarouselItem>
          ))}
        </CarouselContent>
        {total > 1 && (
          <div className="flex items-center justify-between mt-3 px-1">
            <CarouselPrevious className="rounded-full bg-zinc-700 hover:bg-zinc-600 border-none p-1.5 disabled:opacity-40 transition-colors cursor-pointer">
              <ChevronLeft className="w-4 h-4 text-zinc-300" />
            </CarouselPrevious>
            <CarouselDotIndicators />
            <CarouselNext className="rounded-full bg-zinc-700 hover:bg-zinc-600 border-none p-1.5 disabled:opacity-40 transition-colors cursor-pointer">
              <ChevronRight className="w-4 h-4 text-zinc-300" />
            </CarouselNext>
          </div>
        )}
      </Carousel>
    </ToolCard>
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

export const carouselDef = defineComponent({
  name: "Carousel",
  description: "Swipeable card carousel.",
  props: carouselSchema,
  component: ({ props }) => React.createElement(CarouselView, props),
});
