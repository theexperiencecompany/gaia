import { defineComponent, useTriggerAction } from "@openuidev/react-lang";
import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { Image } from "expo-image";
import * as Linking from "expo-linking";
import { useVideoPlayer, VideoView } from "expo-video";
import React from "react";
import {
  Dimensions,
  FlatList,
  Modal,
  Platform,
  Pressable,
  View,
} from "react-native";
import {
  runOnJS,
  useDerivedValue,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import WebView from "react-native-webview";
import { z } from "zod";
import {
  AppIcon,
  ArrowDown01Icon,
  ArrowRight01Icon,
  Cancel01Icon,
  Location01Icon,
  PlayIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  Card,
  InnerCard,
  ItemTitle,
  MutedText,
  SectionTitle,
} from "./primitives";

const CALENDAR_DOT_COLOR: Record<string, string> = {
  success: "#34d399",
  warning: "#fbbf24",
  danger: "#f87171",
  default: "#a1a1aa",
};

const WEEKDAY_INITIALS: { key: string; label: string }[] = [
  { key: "sun", label: "S" },
  { key: "mon", label: "M" },
  { key: "tue", label: "T" },
  { key: "wed", label: "W" },
  { key: "thu", label: "T" },
  { key: "fri", label: "F" },
  { key: "sat", label: "S" },
];

const PRIMARY_COLOR = "#00bbff";

const CAROUSEL_AUTOPLAY_MS = 4000;

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

interface GalleryImg {
  src: string;
  alt?: string;
  caption?: string;
}

interface TreeNode {
  id: string;
  label: string;
  description?: string;
  children?: TreeNode[];
}

interface CarouselAction {
  label: string;
  value: string;
}

interface CarouselItem {
  title: string;
  body?: string;
  image?: string;
  badge?: string;
  actions?: CarouselAction[];
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function parseDateStr(dateStr: string): Date | null {
  const parts = dateStr.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return null;
  const [y, m, d] = parts;
  return new Date(y, m - 1, d);
}

function toDateKey(y: number, m: number, d: number): string {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function ImageBlockView(props: z.infer<typeof imageBlockSchema>) {
  return (
    <View className="w-full">
      <View className="rounded-2xl overflow-hidden">
        <Image
          source={{ uri: props.src }}
          contentFit="cover"
          accessibilityLabel={props.alt}
          style={{ width: "100%", aspectRatio: 16 / 9 }}
        />
      </View>
      {props.caption ? (
        <Text className="text-xs text-zinc-500 mt-2 text-center">
          {props.caption}
        </Text>
      ) : null}
    </View>
  );
}

function GalleryThumb({
  img,
  onPress,
}: {
  img: GalleryImg;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      className="overflow-hidden rounded-2xl"
      style={{ width: "100%", aspectRatio: 1, position: "relative" }}
    >
      <Image
        source={{ uri: img.src }}
        contentFit="cover"
        accessibilityLabel={img.alt}
        style={{ width: "100%", height: "100%" }}
      />
      {img.caption ? (
        <View
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            paddingHorizontal: 12,
            paddingVertical: 8,
            backgroundColor: "rgba(0,0,0,0.55)",
          }}
        >
          <Text className="text-xs font-medium text-white">{img.caption}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

function GalleryLightbox({
  images,
  initialIndex,
  onClose,
}: {
  images: GalleryImg[];
  initialIndex: number;
  onClose: () => void;
}) {
  const { width, height } = Dimensions.get("window");
  const [activeIndex, setActiveIndex] = React.useState(initialIndex);

  return (
    <Modal
      visible
      animationType="fade"
      transparent
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <View
        style={{
          flex: 1,
          backgroundColor: "rgba(0,0,0,0.92)",
          justifyContent: "center",
        }}
      >
        <FlatList
          data={images}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          initialScrollIndex={initialIndex}
          getItemLayout={(_, i) => ({
            length: width,
            offset: width * i,
            index: i,
          })}
          onMomentumScrollEnd={(e) => {
            const idx = Math.round(e.nativeEvent.contentOffset.x / width);
            setActiveIndex(idx);
          }}
          keyExtractor={(item, index) => `${item.src}-${index}`}
          renderItem={({ item }) => (
            <View
              style={{
                width,
                height,
                justifyContent: "center",
                alignItems: "center",
              }}
            >
              <Image
                source={{ uri: item.src }}
                contentFit="contain"
                accessibilityLabel={item.alt}
                style={{ width, height: height * 0.75 }}
              />
              {item.caption ? (
                <Text className="text-sm text-zinc-200 mt-3 px-6 text-center">
                  {item.caption}
                </Text>
              ) : null}
            </View>
          )}
        />
        <View
          style={{
            position: "absolute",
            top: 48,
            left: 0,
            right: 0,
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Text className="text-sm text-zinc-200 tabular-nums">
            {activeIndex + 1} / {images.length}
          </Text>
          <Pressable
            onPress={onClose}
            accessibilityLabel="Close gallery"
            hitSlop={12}
            style={{
              position: "absolute",
              right: 8,
              top: -4,
              padding: 8,
            }}
          >
            <AppIcon icon={Cancel01Icon} size={20} color="#d4d4d8" />
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

export function ImageGalleryView(props: z.infer<typeof imageGallerySchema>) {
  const [selected, setSelected] = React.useState<number | null>(null);
  const images = props.images;

  if (images.length === 0) return null;

  return (
    <View className="w-full">
      <View
        style={{ flexDirection: "row", flexWrap: "wrap", marginHorizontal: -4 }}
      >
        {images.map((img, i) => (
          <View key={`${img.src}-${i}`} style={{ width: "50%", padding: 4 }}>
            <GalleryThumb img={img} onPress={() => setSelected(i)} />
          </View>
        ))}
      </View>
      {selected !== null ? (
        <GalleryLightbox
          images={images}
          initialIndex={selected}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </View>
  );
}

function getEmbedUrl(src: string): string | null {
  if (src.includes("youtube.com") || src.includes("youtu.be")) {
    const match =
      src.match(/[?&]v=([^&]+)/) ??
      src.match(/youtu\.be\/([^?]+)/) ??
      src.match(/embed\/([^?]+)/);
    const videoId = match?.[1];
    if (videoId)
      return `https://www.youtube.com/embed/${videoId}?playsinline=1`;
  } else if (src.includes("vimeo.com")) {
    const match = src.match(/vimeo\.com\/(\d+)/);
    const videoId = match?.[1];
    if (videoId) return `https://player.vimeo.com/video/${videoId}`;
  }
  return null;
}

function NativeVideo({ src }: { src: string }) {
  const player = useVideoPlayer(src);
  return (
    <VideoView
      player={player}
      style={{ width: "100%", height: "100%" }}
      contentFit="contain"
      nativeControls
    />
  );
}

export function VideoBlockView(props: z.infer<typeof videoBlockSchema>) {
  const embedUrl = React.useMemo(() => getEmbedUrl(props.src), [props.src]);

  return (
    <View className="w-full">
      <View
        className="rounded-2xl overflow-hidden"
        style={{ width: "100%", aspectRatio: 16 / 9, backgroundColor: "#000" }}
      >
        {embedUrl ? (
          <WebView
            source={{ uri: embedUrl }}
            style={{ flex: 1, backgroundColor: "transparent" }}
            allowsFullscreenVideo
            javaScriptEnabled
            domStorageEnabled
          />
        ) : (
          <NativeVideo src={props.src} />
        )}
      </View>
      {props.title ? (
        <Text className="text-xs text-zinc-500 mt-2 text-center">
          {props.title}
        </Text>
      ) : null}
    </View>
  );
}

export function AudioPlayerView(props: z.infer<typeof audioPlayerSchema>) {
  const player = useAudioPlayer({ uri: props.src });
  const status = useAudioPlayerStatus(player);
  const isPlaying = status.playing;
  const isLoaded = status.isLoaded;
  const position = status.currentTime;
  const duration = status.duration;

  const toggle = React.useCallback(() => {
    if (!isLoaded) return;
    if (isPlaying) {
      player.pause();
    } else {
      if (duration > 0 && position >= duration) {
        player.seekTo(0);
      }
      player.play();
    }
  }, [player, isLoaded, isPlaying, position, duration]);

  const progress =
    duration > 0 ? Math.min(100, (position / duration) * 100) : 0;

  return (
    <Card>
      {props.title ? <ItemTitle>{props.title}</ItemTitle> : null}
      {props.description ? (
        <View className="mt-1">
          <MutedText>{props.description}</MutedText>
        </View>
      ) : null}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 12,
          marginTop: 12,
        }}
      >
        <Pressable
          onPress={toggle}
          disabled={!isLoaded}
          accessibilityLabel={isPlaying ? "Pause" : "Play"}
          style={{
            width: 40,
            height: 40,
            borderRadius: 9999,
            backgroundColor: "rgba(0, 187, 255, 0.2)",
            alignItems: "center",
            justifyContent: "center",
            opacity: isLoaded ? 1 : 0.4,
          }}
        >
          {isPlaying ? (
            <View style={{ flexDirection: "row", gap: 3 }}>
              <View
                style={{
                  width: 4,
                  height: 14,
                  borderRadius: 1,
                  backgroundColor: PRIMARY_COLOR,
                }}
              />
              <View
                style={{
                  width: 4,
                  height: 14,
                  borderRadius: 1,
                  backgroundColor: PRIMARY_COLOR,
                }}
              />
            </View>
          ) : (
            <AppIcon icon={PlayIcon} size={18} color={PRIMARY_COLOR} />
          )}
        </Pressable>
        <View style={{ flex: 1 }}>
          <View
            style={{
              height: 4,
              borderRadius: 9999,
              backgroundColor: "rgba(63, 63, 70, 0.6)",
              overflow: "hidden",
            }}
          >
            <View
              style={{
                width: `${progress}%`,
                height: "100%",
                backgroundColor: PRIMARY_COLOR,
              }}
            />
          </View>
          <View
            style={{
              flexDirection: "row",
              justifyContent: "space-between",
              marginTop: 8,
            }}
          >
            <Text className="text-xs text-zinc-500 font-mono tabular-nums">
              {formatTime(position)}
            </Text>
            <Text className="text-xs text-zinc-500 font-mono tabular-nums">
              {formatTime(duration)}
            </Text>
          </View>
        </View>
      </View>
    </Card>
  );
}

export function MapBlockView(props: z.infer<typeof mapBlockSchema>) {
  const { lat, lng } = props;
  const zoom = props.zoom ?? 14;

  const embedUrl = React.useMemo(() => {
    const span = 0.5 / 2 ** (zoom - 10);
    const bbox = `${lng - span},${lat - span},${lng + span},${lat + span}`;
    return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lng}`;
  }, [lat, lng, zoom]);

  const openInMaps = React.useCallback(() => {
    const url =
      Platform.OS === "ios"
        ? `http://maps.apple.com/?ll=${lat},${lng}`
        : `geo:${lat},${lng}?q=${lat},${lng}`;
    Linking.openURL(url).catch(() => undefined);
  }, [lat, lng]);

  return (
    <View className="w-full">
      <Pressable onPress={openInMaps}>
        <View
          className="rounded-2xl overflow-hidden"
          style={{
            width: "100%",
            aspectRatio: 16 / 9,
            backgroundColor: "#18181b",
          }}
        >
          <WebView
            source={{ uri: embedUrl }}
            style={{ flex: 1, backgroundColor: "#18181b" }}
            scrollEnabled={false}
            javaScriptEnabled
          />
        </View>
      </Pressable>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          marginTop: 8,
        }}
      >
        <AppIcon icon={Location01Icon} size={14} color="#71717a" />
        {props.label ? (
          <Text className="text-xs text-zinc-500">{props.label}</Text>
        ) : null}
        <Text className="text-xs text-zinc-500 font-mono tabular-nums">
          ({lat.toFixed(4)}, {lng.toFixed(4)})
        </Text>
      </View>
    </View>
  );
}

interface CalendarCell {
  key: string;
  day: number | null;
  dateStr: string | null;
  inMonth: boolean;
}

function buildMonthCells(year: number, month: number): CalendarCell[] {
  const firstDay = new Date(year, month, 1);
  const startOffset = firstDay.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: CalendarCell[] = [];
  for (let i = 0; i < startOffset; i++) {
    cells.push({
      key: `pad-start-${i}`,
      day: null,
      dateStr: null,
      inMonth: false,
    });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({
      key: `d-${d}`,
      day: d,
      dateStr: toDateKey(year, month, d),
      inMonth: true,
    });
  }
  const total = cells.length;
  const trailing = (7 - (total % 7)) % 7;
  for (let i = 0; i < trailing; i++) {
    cells.push({
      key: `pad-end-${i}`,
      day: null,
      dateStr: null,
      inMonth: false,
    });
  }
  return cells;
}

export function CalendarMiniView(props: z.infer<typeof calendarMiniSchema>) {
  const markedMap = React.useMemo(() => {
    const map = new Map<string, string>();
    for (const d of props.markedDates) {
      map.set(d.date, d.color ?? "default");
    }
    return map;
  }, [props.markedDates]);

  const anchorDate = React.useMemo(() => {
    const first =
      props.markedDates.length > 0
        ? parseDateStr(props.markedDates[0].date)
        : null;
    return first ?? new Date();
  }, [props.markedDates]);

  const year = anchorDate.getFullYear();
  const month = anchorDate.getMonth();
  const cells = React.useMemo(
    () => buildMonthCells(year, month),
    [year, month],
  );

  const monthLabel = new Date(year, month, 1).toLocaleString("en-US", {
    month: "long",
    year: "numeric",
  });

  const labeledDates = props.markedDates.filter((d) => d.label);

  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <Text className="text-sm font-medium text-zinc-200 mb-3 text-center">
        {monthLabel}
      </Text>
      <View style={{ flexDirection: "row", marginBottom: 8 }}>
        {WEEKDAY_INITIALS.map((wd) => (
          <View key={wd.key} style={{ flex: 1, alignItems: "center" }}>
            <Text className="text-xs text-zinc-500 text-center">
              {wd.label}
            </Text>
          </View>
        ))}
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
        {cells.map((cell) => {
          const color = cell.dateStr ? markedMap.get(cell.dateStr) : null;
          const dotColor = color
            ? (CALENDAR_DOT_COLOR[color] ?? CALENDAR_DOT_COLOR.default)
            : null;
          return (
            <View
              key={cell.key}
              style={{
                width: `${100 / 7}%`,
                height: 32,
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {cell.day !== null ? (
                <View
                  style={{ alignItems: "center", justifyContent: "center" }}
                >
                  <Text
                    className={
                      cell.inMonth
                        ? "text-xs text-zinc-200 text-center"
                        : "text-xs text-zinc-700 text-center"
                    }
                  >
                    {cell.day}
                  </Text>
                  {dotColor ? (
                    <View
                      style={{
                        width: 4,
                        height: 4,
                        borderRadius: 2,
                        marginTop: 2,
                        backgroundColor: dotColor,
                      }}
                    />
                  ) : (
                    <View style={{ width: 4, height: 4, marginTop: 2 }} />
                  )}
                </View>
              ) : null}
            </View>
          );
        })}
      </View>
      {labeledDates.length > 0 ? (
        <View style={{ marginTop: 12, gap: 6 }}>
          {labeledDates.map((d) => (
            <View
              key={d.date}
              style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
            >
              <View
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor:
                    CALENDAR_DOT_COLOR[d.color ?? "default"] ??
                    CALENDAR_DOT_COLOR.default,
                }}
              />
              <Text className="text-xs text-zinc-200 flex-1">{d.label}</Text>
              <Text className="text-xs text-zinc-500">{d.date}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </Card>
  );
}

export function NumberTickerView(props: z.infer<typeof numberTickerSchema>) {
  const isDecimal = props.value % 1 !== 0;
  const target = props.value;
  const duration = props.duration ?? 1200;

  const shared = useSharedValue(0);
  const [displayValue, setDisplayValue] = React.useState(0);

  React.useEffect(() => {
    shared.value = 0;
    shared.value = withTiming(target, { duration });
  }, [shared, target, duration]);

  useDerivedValue(() => {
    runOnJS(setDisplayValue)(shared.value);
  }, [target]);

  const formatter = React.useMemo(
    () =>
      new Intl.NumberFormat("en-US", {
        minimumFractionDigits: isDecimal ? 1 : 0,
        maximumFractionDigits: isDecimal ? 1 : 0,
        useGrouping: true,
      }),
    [isDecimal],
  );

  return (
    <Card className="items-center">
      {props.label ? (
        <Text className="text-xs text-zinc-500 mb-2 text-center">
          {props.label}
        </Text>
      ) : null}
      <View
        style={{
          flexDirection: "row",
          alignItems: "flex-end",
          justifyContent: "center",
          gap: 4,
        }}
      >
        <Text
          className="font-semibold text-zinc-100"
          style={{ fontSize: 30, lineHeight: 34 }}
        >
          {formatter.format(displayValue)}
        </Text>
        {props.unit ? (
          <Text className="text-sm text-zinc-500" style={{ marginBottom: 2 }}>
            {props.unit}
          </Text>
        ) : null}
      </View>
    </Card>
  );
}

function CarouselSlide({
  item,
  width,
  onAction,
}: {
  item: CarouselItem;
  width: number;
  onAction: (value: string) => void;
}) {
  return (
    <View style={{ width, paddingHorizontal: 4 }}>
      <View
        className="rounded-2xl bg-zinc-800 p-4"
        style={{ flex: 1, gap: 12 }}
      >
        {item.image ? (
          <View
            style={{
              width: "100%",
              aspectRatio: 16 / 9,
              borderRadius: 12,
              overflow: "hidden",
              position: "relative",
            }}
          >
            <Image
              source={{ uri: item.image }}
              contentFit="cover"
              style={{ width: "100%", height: "100%" }}
            />
            {item.badge ? (
              <View
                style={{
                  position: "absolute",
                  top: 12,
                  right: 12,
                  borderRadius: 9999,
                  backgroundColor: "rgba(0, 0, 0, 0.6)",
                  paddingHorizontal: 8,
                  paddingVertical: 2,
                }}
              >
                <Text className="text-xs text-zinc-100">{item.badge}</Text>
              </View>
            ) : null}
          </View>
        ) : null}
        {!item.image && item.badge ? (
          <View
            style={{
              alignSelf: "flex-start",
              borderRadius: 9999,
              backgroundColor: "rgba(0, 0, 0, 0.6)",
              paddingHorizontal: 8,
              paddingVertical: 2,
            }}
          >
            <Text className="text-xs text-zinc-100">{item.badge}</Text>
          </View>
        ) : null}
        <Text className="text-sm font-semibold text-zinc-100">
          {item.title}
        </Text>
        {item.body ? <MutedText>{item.body}</MutedText> : null}
        {item.actions && item.actions.length > 0 ? (
          <View
            style={{
              flexDirection: "row",
              flexWrap: "wrap",
              gap: 8,
              marginTop: "auto",
            }}
          >
            {item.actions.map((action) => (
              <Pressable
                key={action.value}
                onPress={() => onAction(action.value)}
                className="rounded-full bg-zinc-800 active:bg-zinc-700"
                style={{ paddingHorizontal: 12, paddingVertical: 6 }}
              >
                <Text className="text-xs font-medium text-zinc-200">
                  {action.label}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
      </View>
    </View>
  );
}

export function CarouselView(props: z.infer<typeof carouselSchema>) {
  const windowWidth = Dimensions.get("window").width;
  const slideWidth = windowWidth - 32;
  const listRef = React.useRef<FlatList<CarouselItem>>(null);
  const [activeIndex, setActiveIndex] = React.useState(0);
  const total = props.items.length;
  const triggerAction = useTriggerAction();

  const handleAction = React.useCallback(
    (value: string) => {
      triggerAction(value, undefined, {
        type: "continue_conversation",
        params: {},
      });
    },
    [triggerAction],
  );

  React.useEffect(() => {
    if (!props.autoPlay || total <= 1) return;
    const interval = setInterval(() => {
      setActiveIndex((prev) => {
        const next = (prev + 1) % total;
        listRef.current?.scrollToIndex({ index: next, animated: true });
        return next;
      });
    }, CAROUSEL_AUTOPLAY_MS);
    return () => clearInterval(interval);
  }, [props.autoPlay, total]);

  if (total === 0) return null;

  return (
    <View className="w-full">
      <FlatList
        ref={listRef}
        data={props.items}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        keyExtractor={(item, i) => `${item.title}-${i}`}
        getItemLayout={(_, i) => ({
          length: slideWidth,
          offset: slideWidth * i,
          index: i,
        })}
        onMomentumScrollEnd={(e) => {
          const idx = Math.round(e.nativeEvent.contentOffset.x / slideWidth);
          setActiveIndex(idx);
        }}
        renderItem={({ item }) => (
          <CarouselSlide
            item={item}
            width={slideWidth}
            onAction={handleAction}
          />
        )}
      />
      {total > 1 ? (
        <View
          style={{
            flexDirection: "row",
            justifyContent: "center",
            alignItems: "center",
            gap: 6,
            marginTop: 12,
          }}
        >
          {props.items.map((item, i) => (
            <View
              key={`${item.title}-${i}`}
              style={{
                width: 6,
                height: 6,
                borderRadius: 9999,
                backgroundColor: i === activeIndex ? PRIMARY_COLOR : "#3f3f46",
              }}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

function TreeNodeItem({ node, depth }: { node: TreeNode; depth: number }) {
  const [expanded, setExpanded] = React.useState(depth === 0);
  const hasChildren = Boolean(node.children && node.children.length > 0);

  return (
    <View>
      <Pressable
        onPress={() => hasChildren && setExpanded((e) => !e)}
        className="rounded-lg active:bg-zinc-800/60"
        style={{
          flexDirection: "row",
          alignItems: "flex-start",
          gap: 6,
          paddingHorizontal: 8,
          paddingVertical: 4,
          paddingLeft: 8 + depth * 16,
          minHeight: 36,
        }}
      >
        <View
          style={{
            width: 12,
            height: 12,
            marginTop: 4,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {hasChildren ? (
            <AppIcon
              icon={expanded ? ArrowDown01Icon : ArrowRight01Icon}
              size={12}
              color={expanded ? "#a1a1aa" : "#71717a"}
            />
          ) : (
            <View
              style={{
                width: 4,
                height: 4,
                borderRadius: 2,
                backgroundColor: "#52525b",
              }}
            />
          )}
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text
            className={
              hasChildren
                ? "text-sm font-medium text-zinc-200"
                : "text-sm text-zinc-400"
            }
          >
            {node.label}
          </Text>
          {node.description ? (
            <Text className="text-xs text-zinc-500 mt-0.5">
              {node.description}
            </Text>
          ) : null}
        </View>
      </Pressable>
      {expanded && hasChildren ? (
        <View>
          {node.children?.map((child) => (
            <TreeNodeItem
              key={child.id}
              node={child as TreeNode}
              depth={depth + 1}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

export function TreeViewView(props: z.infer<typeof treeViewSchema>) {
  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <InnerCard>
        {props.nodes.map((node) => (
          <TreeNodeItem key={node.id} node={node as TreeNode} depth={0} />
        ))}
      </InnerCard>
    </Card>
  );
}

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
