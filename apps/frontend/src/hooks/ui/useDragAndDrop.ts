import { useCallback, useState } from "react";

export interface UseDragAndDropOptions {
  onDrop: (files: File[]) => void;
  accept?: string[];
  multiple?: boolean;
  disabled?: boolean;
}

export interface UseDragAndDropReturn {
  isDragging: boolean;
  dragHandlers: {
    onDragEnter: (e: React.DragEvent<HTMLElement>) => void;
    onDragOver: (e: React.DragEvent<HTMLElement>) => void;
    onDragLeave: (e: React.DragEvent<HTMLElement>) => void;
    onDrop: (e: React.DragEvent<HTMLElement>) => void;
  };
  setIsDragging: (dragging: boolean) => void;
}

export function useDragAndDrop({
  onDrop,
  accept,
  multiple = true,
  disabled = false,
}: UseDragAndDropOptions): UseDragAndDropReturn {
  const [isDragging, setIsDragging] = useState(false);

  const validateFiles = useCallback(
    (files: FileList) => {
      if (!multiple && files.length > 1) {
        return false;
      }

      if (accept && accept.length > 0) {
        const validFiles = Array.from(files).filter((file) => {
          return accept.some((acceptedType) => {
            if (acceptedType.startsWith(".")) {
              // Handle file extensions like .pdf, .txt
              return file.name
                .toLowerCase()
                .endsWith(acceptedType.toLowerCase());
            } else if (acceptedType.includes("/*")) {
              // Handle MIME types like image/*, application/*
              const mimePattern = acceptedType.replace("*", ".*");
              return new RegExp(mimePattern).test(file.type);
            } else {
              // Handle exact MIME types like image/jpeg, application/pdf
              return file.type === acceptedType;
            }
          });
        });
        return validFiles.length === files.length;
      }

      return true;
    },
    [accept, multiple],
  );

  const handleDragEnter = useCallback(
    (e: React.DragEvent<HTMLElement>) => {
      if (disabled) return;

      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
    },
    [disabled],
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent<HTMLElement>) => {
      if (disabled) return;

      e.preventDefault();
      e.stopPropagation();
      if (!isDragging) setIsDragging(true);
    },
    [disabled, isDragging],
  );

  const handleDragLeave = useCallback(
    (e: React.DragEvent<HTMLElement>) => {
      if (disabled) return;

      e.preventDefault();
      e.stopPropagation();

      // Only set isDragging to false if we're leaving the main container
      // rather than entering a child element
      if (e.currentTarget.contains(e.relatedTarget as Node)) {
        return;
      }
      setIsDragging(false);
    },
    [disabled],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLElement>) => {
      if (disabled) return;

      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        const files = Array.from(e.dataTransfer.files);

        if (validateFiles(e.dataTransfer.files)) {
          onDrop(files);
        } else {
          console.warn(
            "Some files were rejected due to type or count restrictions",
          );
          // Only pass valid files
          if (accept && accept.length > 0) {
            const validFiles = files.filter((file) => {
              return accept.some((acceptedType) => {
                if (acceptedType.startsWith(".")) {
                  return file.name
                    .toLowerCase()
                    .endsWith(acceptedType.toLowerCase());
                } else if (acceptedType.includes("/*")) {
                  const mimePattern = acceptedType.replace("*", ".*");
                  return new RegExp(mimePattern).test(file.type);
                } else {
                  return file.type === acceptedType;
                }
              });
            });

            if (validFiles.length > 0) {
              const filesToProcess = multiple
                ? validFiles
                : validFiles.slice(0, 1);
              onDrop(filesToProcess);
            }
          }
        }
      }
    },
    [disabled, onDrop, validateFiles, accept, multiple],
  );

  return {
    isDragging,
    dragHandlers: {
      onDragEnter: handleDragEnter,
      onDragOver: handleDragOver,
      onDragLeave: handleDragLeave,
      onDrop: handleDrop,
    },
    setIsDragging,
  };
}
