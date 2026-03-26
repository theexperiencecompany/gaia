import { Calendar, type DateValue } from "@heroui/calendar";
import { Button, Chip } from "@heroui/react";
import { ArrowDown01Icon, ArrowRight01Icon } from "@icons";
import { CalendarDate } from "@internationalized/date";
import { defineComponent } from "@openuidev/react-lang";
import { motion } from "motion/react";
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
import { NumberTicker } from "@/components/ui/number-ticker";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CALENDAR_DOT_COLOR: Record<string, string> = {
  success: "#34d399",
  warning: "#fbbf24",
  danger: "#f87171",
  default: "#a1a1aa",
};

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

export const imageBlockSchema = z.object({
  src: z.string(),
  alt: z.string().optional(),
  caption: z.string().optional(),
});

export const imageGallerySchema = z.object({
  images: z.array(
    z.object({
      src: z.string(),
      alt: z.string().optional(),
      caption: z.string().optional(),
    }),
  ),
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

export const mapBlockSchema = z.object({
  lat: z.number(),
  lng: z.number(),
  label: z.string().optional(),
  zoom: z.number().optional(),
});

export const calendarMiniSchema = z.object({
  markedDates: z.array(
    z.object({
      date: z.string(),
      label: z.string().optional(),
      color: z.enum(["success", "warning", "danger", "default"]).optional(),
    }),
  ),
  title: z.string().optional(),
  mode: z.enum(["single", "range"]).optional(),
});

export const numberTickerSchema = z.object({
  value: z.number(),
  label: z.string().optional(),
  unit: z.string().optional(),
  duration: z.number().optional(),
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

export const treeViewSchema = z.object({
  nodes: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      description: z.string().optional(),
      children: z.array(z.unknown()).optional(),
    }),
  ),
  title: z.string().optional(),
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dateStrToCalendarDate(dateStr: string): CalendarDate {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new CalendarDate(y, m, d);
}

function GalleryImage({
  img,
}: {
  img: { src: string; alt?: string; caption?: string };
}) {
  return (
    <motion.div
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="relative overflow-hidden rounded-xl cursor-pointer"
      style={{ aspectRatio: "3/2" }}
    >
      {/* biome-ignore lint/performance/noImgElement: external user-provided URLs */}
      <img
        src={img.src}
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
    </motion.div>
  );
}

interface TreeNode {
  id: string;
  label: string;
  description?: string;
  children?: TreeNode[];
}

function TreeNodeItem({ node, depth }: { node: TreeNode; depth: number }) {
  const [expanded, setExpanded] = React.useState(depth === 0);
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div>
      <div
        className="flex items-start gap-1.5 py-1 cursor-pointer select-none"
        style={{ paddingLeft: `${depth * 16}px` }}
        onClick={() => hasChildren && setExpanded((e) => !e)}
      >
        <span className="mt-0.5 w-3.5 h-3.5 shrink-0 flex items-center justify-center">
          {hasChildren ? (
            <span className="cursor-pointer">
              {expanded ? (
                <ArrowDown01Icon className="w-3 h-3 text-zinc-400" />
              ) : (
                <ArrowRight01Icon className="w-3 h-3 text-zinc-500" />
              )}
            </span>
          ) : (
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-700 inline-block mt-0.5" />
          )}
        </span>
        <div className="flex-1 min-w-0">
          <span
            className={
              hasChildren
                ? "text-sm font-medium text-zinc-300"
                : "text-sm text-zinc-400"
            }
          >
            {node.label}
          </span>
          {node.description && (
            <span className="text-xs text-zinc-600 ml-2">
              {node.description}
            </span>
          )}
        </div>
      </div>
      {expanded && hasChildren && (
        <div className="ml-3 border-l border-zinc-800 pl-1">
          {node.children?.map((child) => (
            <TreeNodeItem
              key={child.id}
              node={child as TreeNode}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
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

export function ImageBlockView(props: z.infer<typeof imageBlockSchema>) {
  return (
    <div className="rounded-2xl overflow-hidden">
      {/* biome-ignore lint/performance/noImgElement: external user-provided URLs */}
      <img
        src={props.src}
        alt={props.alt ?? ""}
        className="w-full object-cover max-h-96"
      />
      {props.caption && (
        <p className="text-xs text-zinc-500 mt-2 text-center">
          {props.caption}
        </p>
      )}
    </div>
  );
}

export function ImageGalleryView(props: z.infer<typeof imageGallerySchema>) {
  const images = props.images;
  const count = images.length;

  if (count === 1) {
    return <GalleryImage img={images[0]} />;
  }

  if (count === 2) {
    return (
      <div className="grid grid-cols-2 gap-1.5">
        {images.map((img) => (
          <GalleryImage key={img.src} img={img} />
        ))}
      </div>
    );
  }

  if (count === 3) {
    return (
      <div className="grid grid-cols-2 gap-1.5">
        <GalleryImage img={images[0]} />
        <GalleryImage img={images[1]} />
        <div className="col-span-2">
          <GalleryImage img={images[2]} />
        </div>
      </div>
    );
  }

  if (count === 4) {
    return (
      <div className="grid grid-cols-2 gap-1.5">
        {images.map((img) => (
          <GalleryImage key={img.src} img={img} />
        ))}
      </div>
    );
  }

  const topRow = images.slice(0, 3);
  const bottomRow = images.slice(3);

  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-3 gap-1.5">
        {topRow.map((img) => (
          <GalleryImage key={img.src} img={img} />
        ))}
      </div>
      {bottomRow.length > 0 && (
        <div
          className={`grid grid-cols-${Math.min(bottomRow.length, 3)} gap-1.5`}
        >
          {bottomRow.map((img) => (
            <GalleryImage key={img.src} img={img} />
          ))}
        </div>
      )}
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

  return (
    <div className="w-full min-w-fit max-w-xl">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      {isEmbed ? (
        <iframe
          src={embedSrc}
          className="w-full rounded-2xl aspect-video"
          style={{ border: "none" }}
          allowFullScreen
          title={props.title ?? "video"}
        />
      ) : (
        <video
          src={src}
          poster={props.poster}
          controls
          className="w-full rounded-2xl aspect-video object-cover"
        >
          <track kind="captions" />
        </video>
      )}
    </div>
  );
}

export function AudioPlayerView(props: z.infer<typeof audioPlayerSchema>) {
  return (
    <div className="w-full min-w-fit max-w-xl">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-1">
          {props.title}
        </p>
      )}
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      <audio src={props.src} controls className="w-full mt-2">
        <track kind="captions" />
      </audio>
    </div>
  );
}

export function MapBlockView(props: z.infer<typeof mapBlockSchema>) {
  const { lat, lng } = props;
  const zoom = props.zoom ?? 14;
  const bbox = (() => {
    // Calculate bbox from zoom — higher zoom = smaller area
    const span = 0.5 / 2 ** (zoom - 10);
    return `${lng - span},${lat - span},${lng + span},${lat + span}`;
  })();
  const src = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lng}`;

  return (
    <div className="rounded-2xl bg-zinc-800 p-3 w-full max-w-lg">
      {props.label && (
        <div className="flex items-center gap-2 px-1 mb-2">
          <div className="h-2 w-2 rounded-full bg-primary" />
          <p className="text-sm font-medium text-zinc-100">{props.label}</p>
          <span className="text-xs text-zinc-500 ml-auto tabular-nums">
            {lat.toFixed(4)}, {lng.toFixed(4)}
          </span>
        </div>
      )}
      <iframe
        src={src}
        className="w-full rounded-xl"
        style={{ height: 220, border: "none" }}
        title={props.label ?? "map"}
      />
    </div>
  );
}

export function CalendarMiniView(props: z.infer<typeof calendarMiniSchema>) {
  const markedSet = new Set(props.markedDates.map((d) => d.date));
  const today = new Date();
  const firstDate =
    props.markedDates.length > 0
      ? dateStrToCalendarDate(props.markedDates[0].date)
      : new CalendarDate(
          today.getFullYear(),
          today.getMonth() + 1,
          today.getDate(),
        );

  return (
    <div>
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <Calendar
        isReadOnly
        defaultValue={firstDate as unknown as DateValue}
        topContent={null}
        bottomContent={null}
        isDateUnavailable={(date: DateValue) => {
          const str = `${date.year}-${String(date.month).padStart(2, "0")}-${String(date.day).padStart(2, "0")}`;
          return !markedSet.has(str);
        }}
      />
      {props.markedDates.some((d) => d.label) && (
        <div className="mt-2 space-y-1">
          {props.markedDates
            .filter((d) => d.label)
            .map((d) => (
              <div key={d.date} className="flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{
                    backgroundColor: CALENDAR_DOT_COLOR[d.color ?? "default"],
                  }}
                />
                <span className="text-xs text-zinc-300">{d.label}</span>
                <span className="text-xs text-zinc-500 ml-auto">{d.date}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

export function NumberTickerView(props: z.infer<typeof numberTickerSchema>) {
  const isDecimal = props.value % 1 !== 0;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 text-center min-w-28">
      {props.label && (
        <p className="text-xs text-zinc-500 mb-2">{props.label}</p>
      )}
      <div className="flex items-end justify-center gap-1">
        <span className="text-3xl font-semibold text-zinc-100">
          <NumberTicker value={props.value} decimalPlaces={isDecimal ? 1 : 0} />
        </span>
        {props.unit && (
          <span className="text-sm text-zinc-500 mb-0.5">{props.unit}</span>
        )}
      </div>
    </div>
  );
}

export function CarouselView(props: z.infer<typeof carouselSchema>) {
  const handleAction = (value: string) => {
    window.dispatchEvent(
      new CustomEvent("openui:action", {
        detail: { type: "continue_conversation", value },
      }),
    );
  };

  const total = props.items.length;

  return (
    <div>
      <Carousel opts={{ align: "start", loop: true }}>
        <CarouselContent className="-ml-0">
          {props.items.map((item) => (
            <CarouselItem key={item.title} className="pl-0 h-full">
              <div className="rounded-2xl bg-zinc-800 p-4 min-h-full flex flex-col">
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
              </div>
            </CarouselItem>
          ))}
        </CarouselContent>
        {total > 1 && (
          <div className="flex items-center justify-between mt-3 px-1">
            <CarouselPrevious className="rounded-full bg-zinc-800 hover:bg-zinc-700 border-none p-1.5 disabled:opacity-40 transition-colors cursor-pointer">
              <ChevronLeft className="w-4 h-4 text-zinc-300" />
            </CarouselPrevious>
            <CarouselDotIndicators />
            <CarouselNext className="rounded-full bg-zinc-800 hover:bg-zinc-700 border-none p-1.5 disabled:opacity-40 transition-colors cursor-pointer">
              <ChevronRight className="w-4 h-4 text-zinc-300" />
            </CarouselNext>
          </div>
        )}
      </Carousel>
    </div>
  );
}

export function TreeViewView(props: z.infer<typeof treeViewSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="rounded-2xl bg-zinc-900 p-3">
        {props.nodes.map((node) => (
          <TreeNodeItem key={node.id} node={node as TreeNode} depth={0} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

export const imageBlockDef = defineComponent({
  name: "ImageBlock",
  description: "Single image with optional caption.",
  props: imageBlockSchema,
  component: ({ props }) => React.createElement(ImageBlockView, props),
});

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

export const calendarMiniDef = defineComponent({
  name: "CalendarMini",
  description: "Mini calendar with marked dates.",
  props: calendarMiniSchema,
  component: ({ props }) => React.createElement(CalendarMiniView, props),
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

export const treeViewDef = defineComponent({
  name: "TreeView",
  description: "Collapsible tree of nested nodes.",
  props: treeViewSchema,
  component: ({ props }) => React.createElement(TreeViewView, props),
});
