/**
 * Content components — re-exported from the OpenUI config layer.
 *
 * The implementations live in:
 *   apps/mobile/src/config/openui/components/content.tsx
 *
 * Notable mobile-specific behaviours vs. web:
 * - ImageGallery opens a full-screen Modal lightbox on tap
 * - VideoBlock uses expo-av for native video; YouTube/Vimeo fall back to WebView
 * - AudioPlayer uses expo-av with a native playback engine
 * - MapBlock renders OpenStreetMap in a WebView and opens native Maps on tap
 * - CalendarMini is a pure React Native grid (no @heroui/calendar dependency)
 * - NumberTicker animates via react-native-reanimated shared values
 * - Carousel is a FlatList with paging and optional autoPlay
 */
export {
  AudioPlayerView,
  audioPlayerDef,
  audioPlayerSchema,
  CalendarMiniView,
  CarouselView,
  calendarMiniDef,
  calendarMiniSchema,
  carouselDef,
  carouselSchema,
  ImageBlockView,
  ImageGalleryView,
  imageBlockDef,
  imageBlockSchema,
  imageGalleryDef,
  imageGallerySchema,
  MapBlockView,
  mapBlockDef,
  mapBlockSchema,
  NumberTickerView,
  numberTickerDef,
  numberTickerSchema,
  TreeViewView,
  treeViewDef,
  treeViewSchema,
  VideoBlockView,
  videoBlockDef,
  videoBlockSchema,
} from "@/config/openui/components/content";
