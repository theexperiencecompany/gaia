// Search-related types based on Tavily's API format

export type WebResult = {
  title: string;
  url: string;
  content: string;
  score: number;
  raw_content?: string;
  favicon?: string;
};

export type NewsResult = {
  title: string;
  url: string;
  content: string;
  score: number;
  raw_content?: string;
  favicon?: string;
};

// Tavily returns images as simple URL strings
export type ImageResult = string;

// Define the overall SearchResults type
export type SearchResults = {
  web?: WebResult[];
  images?: ImageResult[];
  news?: NewsResult[];
  answer?: string;
  query?: string;
  response_time?: number;
  request_id?: string;
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
