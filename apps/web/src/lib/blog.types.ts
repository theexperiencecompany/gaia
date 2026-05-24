export interface Author {
  name: string;
  role: string;
  avatar: string;
  linkedin?: string;
  twitter?: string;
}

export interface BlogPost {
  slug: string;
  title: string;
  date: string;
  authors: Author[];
  category: string;
  image: string;
  content: string;
  featured?: boolean;
}

/** BlogPost without content — safe to pass across RSC→client boundaries */
export type BlogPostMeta = Omit<BlogPost, "content">;

export interface BlogPostFrontmatter {
  title: string;
  date: string;
  authors: Author[];
  category: string;
  image: string;
  slug: string;
  featured?: boolean;
}
