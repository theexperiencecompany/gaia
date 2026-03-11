export interface FileData {
  id?: string;
  name: string;
  url: string;
  type: string;
  size?: number;
  mimeType?: string;
}

export interface ImageData {
  url: string;
  width?: number;
  height?: number;
  alt?: string;
  thumbnailUrl?: string;
}

export interface FileUploadResult {
  fileId: string;
  url: string;
  name: string;
  size: number;
}
