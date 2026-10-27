export interface Author {
  name: string;
  role: string;
  avatar: string;
  linkedin?: string;
  twitter?: string;
  github?: string;
}

export interface BlogContentPost {
  slug: string;
  title: string;
  /** Search-result title from frontmatter `metaTitle:`, for a post whose title is too short to describe it. */
  metaTitle?: string;
  date: string;
  /** Revision date from frontmatter `updated:` — absent means never revised. */
  updated?: string;
  authors: Author[];
  category: string;
  image: string;
  content: string;
  featured?: boolean;
}

/** BlogContentPost without content — safe to pass across RSC→client boundaries */
export type BlogPostMeta = Omit<BlogContentPost, "content">;
