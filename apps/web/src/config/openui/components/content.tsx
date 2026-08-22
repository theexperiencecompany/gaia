import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import {
  audioPlayerSchema,
  imageGallerySchema,
  mapBlockSchema,
  numberTickerSchema,
  videoBlockSchema,
} from "../promptSpecs";
import { AudioPlayerView } from "./AudioPlayerView";
import { ImageGalleryView } from "./ImageGalleryView";
import { MapBlockView } from "./MapBlockView";
import { NumberTickerView } from "./NumberTickerView";
import { VideoBlockView } from "./VideoBlockView";

// ---------------------------------------------------------------------------
// Component definitions
//
// This module is the registration surface consumed by ../genericLibrary; the
// views themselves live in their own files next to this one.
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
