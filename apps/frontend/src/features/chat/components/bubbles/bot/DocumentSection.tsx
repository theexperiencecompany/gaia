import { Button } from "@heroui/button";
import { Card, CardBody } from "@heroui/card";
import { Chip } from "@heroui/chip";
import type React from "react";

import { Download01Icon, File01Icon } from "@/icons";
import type { DocumentData } from "@/types/features/convoTypes";

interface DocumentSectionProps {
  document_data: DocumentData;
}

const DocumentSection: React.FC<DocumentSectionProps> = ({ document_data }) => {
  const handleDownload = async () => {
    try {
      // Fetch the file content
      const response = await fetch(document_data.url);

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // Get the blob data
      const blob = await response.blob();

      // Create a blob URL
      const blobUrl = window.URL.createObjectURL(blob);

      // Create a temporary anchor element to trigger download
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = document_data.filename;
      link.style.display = "none";

      // Append to body, click, and remove
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      // Clean up the blob URL
      window.URL.revokeObjectURL(blobUrl);
    } catch (error) {
      console.error("Error downloading document:", error);
      // Fallback: try direct download with anchor
      try {
        const link = document.createElement("a");
        link.href = document_data.url;
        link.download = document_data.filename;
        link.setAttribute("target", "_blank");
        link.setAttribute("rel", "noopener noreferrer");
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      } catch (fallbackError) {
        console.error("Fallback download failed:", fallbackError);
        // Last resort: open in new tab
        window.open(document_data.url, "_blank");
      }
    }
  };

  const getFileExtension = (filename: string) => {
    return filename.split(".").pop()?.toLowerCase() || "";
  };

  const getFileTypeChipColor = (filename: string) => {
    const extension = getFileExtension(filename);
    switch (extension) {
      case "pdf":
        return "danger";
      case "doc":
      case "docx":
        return "primary";
      case "txt":
        return "default";
      case "md":
        return "secondary";
      default:
        return "default";
    }
  };

  return (
    <div className="mt-3">
      <Card className="border-zinc-700 bg-zinc-800">
        <CardBody className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <div className="flex-shrink-0">
                <File01Icon className="text-primary" size={24} />
              </div>

              <div className="min-w-0 flex-1">
                <div className="mb-1 flex items-center gap-2">
                  <h4 className="truncate text-sm font-medium text-white">
                    {document_data.title || document_data.filename}
                  </h4>
                  <Chip
                    size="sm"
                    variant="flat"
                    color={getFileTypeChipColor(document_data.filename)}
                    className="text-xs"
                  >
                    {getFileExtension(document_data.filename).toUpperCase()}
                  </Chip>
                </div>

                {document_data.title && (
                  <p className="truncate text-sm text-zinc-400">
                    {document_data.filename}
                  </p>
                )}
              </div>
            </div>

            <Button
              color="primary"
              variant="flat"
              size="sm"
              startContent={<Download01Icon size={16} />}
              onClick={handleDownload}
              className="ml-3 flex-shrink-0"
            >
              Download
            </Button>
          </div>
        </CardBody>
      </Card>
    </div>
  );
};

export default DocumentSection;
