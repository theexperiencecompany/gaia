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
  authors: Author[];
  category: string;
  image: string;
  content: string;
  featured?: boolean;
}

/** BlogContentPost without content — safe to pass across RSC→client boundaries */
export type BlogPostMeta = Omit<BlogContentPost, "content">;
