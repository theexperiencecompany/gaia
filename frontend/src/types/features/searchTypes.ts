// Search-related types for web search functionality

export type WebResult = {
  title: string;
  url: string;
  snippet: string;
  source: string;
  date: string;
};

export type ImageResult = {
  title: string;
  url: string;
  source: string;
  thumbnail?: string;
};

export type NewsResult = {
  title: string;
  url: string;
  snippet: string;
  source: string;
  date: string;
};

export type VideoResult = {
  title: string;
  url: string;
  thumbnail: string;
  source: string;
};

// Define the overall SearchResults type.
export type SearchResults = {
  web?: WebResult[];
  images?: ImageResult[];
  news?: NewsResult[];
  videos?: VideoResult[];
};

// Enhanced result including full_content and screenshot_url
export type EnhancedWebResult = WebResult & {
  full_content?: string;
  screenshot_url?: string;
};

// Define the DeepResearchResults type for deep research results
export type DeepResearchResults = {
  original_search?: SearchResults;
  enhanced_results?: EnhancedWebResult[];
  screenshots_taken?: boolean;
  metadata?: {
    total_content_size?: number;
    elapsed_time?: number;
    query?: string;
  };
};
