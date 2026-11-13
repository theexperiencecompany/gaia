import type { z } from "zod";
import type { videoBlockSchema } from "../promptSpecs";

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
    // Third-party embed of an LLM-supplied URL — sandboxed to only what
    // playback needs (own scripts/storage, popups); no forms, no top nav.
    // Cross-origin, so `allow-same-origin` grants only the player's own storage.
    <iframe
      src={embedSrc}
      className="w-full max-w-2xl rounded-2xl aspect-video"
      style={{ border: "none" }}
      sandbox="allow-scripts allow-same-origin allow-presentation allow-popups"
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
