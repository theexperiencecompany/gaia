export interface Author {
  name: string;
  role: string;
  avatar: string;
  linkedin?: string;
  twitter?: string;
}

export interface BlogContentPost {
  slug: string;
  title: string;
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
