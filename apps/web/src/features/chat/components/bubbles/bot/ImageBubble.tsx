// ImageBubble.tsx
import { Skeleton } from "@heroui/skeleton";
import Image from "next/image";

import type { ImageData } from "@/types";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";

interface ImageBubbleProps
  extends Pick<
    ChatBubbleBotProps,
    "text" | "loading" | "setOpenImage" | "setImageData"
  > {
  image_data?: ImageData;
}

export default function ImageBubble({
  text,
  loading,
  image_data,
  setOpenImage,
  setImageData,
}: ImageBubbleProps) {
  // Only use image_data for image information
  if (!image_data?.url && !loading) return null;

  return (
    <>
      <Skeleton
        className="mb-4 aspect-square max-h-[350px] min-h-[350px] max-w-[350px] min-w-[350px] overflow-hidden rounded-3xl"
        isLoaded={!loading && Boolean(image_data?.url)}
      >
        {image_data?.url && (
          <Image
            alt="Generated Image"
            className="my-2 cursor-pointer! rounded-3xl"
            height={500}
            width={500}
            src={image_data.url}
            onClick={() => {
              setOpenImage(true);
              setImageData({
                src: image_data.url,
                prompt: image_data.prompt || "",
                improvedPrompt: image_data.improved_prompt || "",
              });
            }}
          />
        )}
      </Skeleton>
      {text.trim() && (
        <div className="chat_bubble bg-surface-200">
          <span>{text}</span>
        </div>
      )}
    </>
  );
}
