import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import React from "react";
import { toast } from "sonner";

import { Cancel01Icon, DownloadSquare01Icon } from "@/icons";
import { ImageData } from "@/types/features/toolDataTypes";

interface ChatBubbleActionsImageProps {
  fullWidth?: boolean;
  setOpenImage?: React.Dispatch<React.SetStateAction<boolean>>;
  image_data: ImageData; // Required image_data with no fallbacks
}

export default function ChatBubble_Actions_Image({
  fullWidth = false,
  setOpenImage,
  image_data,
}: ChatBubbleActionsImageProps) {
  const downloadFromSrc = async () => {
    try {
      // Get current date and time for filename
      const now = new Date();
      const date = now.toISOString().split("T")[0];
      const time = now.toTimeString().split(" ")[0].replace(/:/g, "-");

      // Sanitize and truncate the prompt
      const sanitizedPrompt = image_data.prompt
        ?.replace(/[^\w\s-]/g, "")
        .slice(0, 50);
      const fileName = `GAIA ${date} ${time} ${sanitizedPrompt}.png`;

      // Fetch the image as a blob
      const response = await fetch(image_data.url);
      const blob = await response.blob();

      // Create URL from blob
      const blobUrl = window.URL.createObjectURL(blob);

      // Create download link
      const downloadLink = document.createElement("a");
      downloadLink.href = blobUrl;
      downloadLink.download = fileName;

      // Trigger download
      document.body.appendChild(downloadLink);
      downloadLink.click();

      // Cleanup
      document.body.removeChild(downloadLink);
      window.URL.revokeObjectURL(blobUrl);
    } catch (error) {
      console.error("Error downloading image:", error);
      toast.error("Failed to download image", {
        description: "Please try again later",
      });
    }
  };

  return (
    <div className="flex w-fit items-center gap-2 pl-1">
      {fullWidth && setOpenImage ? (
        <Button variant="flat" onPress={() => setOpenImage(false)}>
          <Cancel01Icon height="22" />
          <span>Cancel</span>
        </Button>
      ) : (
        <></>
      )}
      <Tooltip
        className={`${fullWidth ? "hidden" : ""}`}
        color="primary"
        content="Download Image"
        placement="right"
        size="md"
      >
        <Button
          className={`w-fit ${
            fullWidth
              ? "px-3 py-2"
              : "bg-transparent p-0 text-zinc-500 data-[hover=true]:bg-transparent"
          } h-fit rounded-lg`}
          color="primary"
          isIconOnly={!fullWidth}
          style={{ minWidth: "22px" }}
          variant={fullWidth ? "solid" : "light"}
          onPress={downloadFromSrc}
        >
          <DownloadSquare01Icon className={`cursor-pointer`} height="22" />
          <span className="text-black">{fullWidth ? "Download" : ""}</span>
        </Button>
      </Tooltip>
    </div>
  );
}
