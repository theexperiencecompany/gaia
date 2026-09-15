/**
 * Content components re-exported from
 * apps/mobile/src/config/openui/components/content.tsx. Mobile-specific:
 * ImageGallery opens a full-screen Modal; VideoBlock uses expo-av (YouTube/Vimeo
 * fall back to WebView); AudioPlayer uses expo-av; MapBlock renders OpenStreetMap
 * in a WebView; CalendarMini is a pure RN grid; Carousel is a paged FlatList.
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
