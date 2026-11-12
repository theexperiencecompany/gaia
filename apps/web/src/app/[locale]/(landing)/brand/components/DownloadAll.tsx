"use client";

import { Download01Icon } from "@icons";
import { GaiaButton } from "@/components/shared/GaiaButton";

function downloadAllAssets() {
  const link = document.createElement("a");
  link.href = "/brand/brand-assets.zip";
  link.download = "the-experience-company-brand-assets.zip";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

export function DownloadAll() {
  return (
    <GaiaButton onPress={downloadAllAssets} variant="primary">
      <Download01Icon className="h-5 w-5" />
      Download All Assets
    </GaiaButton>
  );
}
