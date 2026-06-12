/**
 * Screen capture for the desktop tool bridge.
 *
 * Captures the display the user is currently on (the one under the
 * cursor — not always the primary) at native resolution, then produces
 * two encodings: a PNG sized for model vision (long edge capped so
 * providers don't re-downscale unpredictably) and a small JPEG thumbnail
 * for the chat UI card.
 *
 * @module tools/screenshot
 */

import type { DesktopScreenshotData } from "@gaia/shared/desktop-tools";
import { desktopCapturer, screen, systemPreferences } from "electron";

/** Long-edge cap for the model-facing image (Anthropic/OpenAI-safe). */
const MODEL_IMAGE_MAX_EDGE = 1568;
/** Width of the chat-card thumbnail. */
const THUMBNAIL_WIDTH = 512;
const THUMBNAIL_JPEG_QUALITY = 70;

/** Thrown with a typed message the backend turns into a permission hint. */
export const SCREEN_PERMISSION_ERROR = "permission_denied:screen";

export async function captureScreenshot(): Promise<DesktopScreenshotData> {
  if (
    process.platform === "darwin" &&
    systemPreferences.getMediaAccessStatus("screen") !== "granted"
  ) {
    throw new Error(SCREEN_PERMISSION_ERROR);
  }

  // The display under the cursor is where the user is actually working —
  // on a multi-monitor setup the primary display is often the wrong screen.
  const target = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const physicalSize = {
    width: Math.round(target.size.width * target.scaleFactor),
    height: Math.round(target.size.height * target.scaleFactor),
  };

  const sources = await desktopCapturer.getSources({
    types: ["screen"],
    thumbnailSize: physicalSize,
  });
  const source =
    sources.find((s) => s.display_id === String(target.id)) ?? sources[0];
  if (!source || source.thumbnail.isEmpty()) {
    throw new Error("Screen capture returned no image");
  }

  const captured = source.thumbnail;
  const { width: sourceWidth, height: sourceHeight } = captured.getSize();

  const scale = Math.min(
    1,
    MODEL_IMAGE_MAX_EDGE / Math.max(sourceWidth, sourceHeight),
  );
  const modelImage =
    scale < 1
      ? captured.resize({ width: Math.round(sourceWidth * scale) })
      : captured;
  const { width, height } = modelImage.getSize();

  const thumbnail = captured.resize({ width: THUMBNAIL_WIDTH });

  return {
    image_b64: modelImage.toPNG().toString("base64"),
    thumbnail_b64: thumbnail.toJPEG(THUMBNAIL_JPEG_QUALITY).toString("base64"),
    width,
    height,
    source_width: sourceWidth,
    source_height: sourceHeight,
  };
}
