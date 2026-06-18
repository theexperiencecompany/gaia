/** Chat-card payload emitted by the backend's take_screenshot tool. */
export interface ScreenshotData {
  /** JPEG thumbnail as a data URL. */
  thumbnail: string;
  width?: number;
  height?: number;
}
