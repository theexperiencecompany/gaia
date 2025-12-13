"use client";

import { Button } from "@heroui/button";
import { Download01Icon } from "@/components";

export function DownloadAll() {
  const handleDownloadAll = () => {
    const link = document.createElement("a");
    link.href = "/brand/brand-assets.zip";
    link.download = "the-experience-company-brand-assets.zip";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <Button
      onPress={handleDownloadAll}
      color="primary"
      startContent={<Download01Icon className="h-5 w-5" />}
    >
      Download All Assets
    </Button>
  );
}
