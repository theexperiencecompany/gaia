"use server";

import fs from "fs";
import matter from "gray-matter";
import path from "path";

const postsDirectory = path.join(process.cwd(), "content/blog");

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

export interface BlogPostFrontmatter {
  title: string;
  date: string;
  authors: Author[];
  category: string;
  image: string;
  slug: string;
  featured?: boolean;
}

/**
 * Get all blog post slugs
 */
export async function getAllBlogSlugs(): Promise<string[]> {
  try {
    const files = fs.readdirSync(postsDirectory);
    return files
      .filter((file) => file.endsWith(".mdx") || file.endsWith(".md"))
      .map((file) => file.replace(/\.(mdx|md)$/, ""))
      .filter((slug) => !["README", "TEMPLATE"].includes(slug));
  } catch (error) {
    console.error("Error reading blog directory:", error);
    return [];
  }
}

/**
 * Get a single blog post by slug
 */
export async function getBlogPost(slug: string): Promise<BlogPost | null> {
  try {
    const fullPath = path.join(postsDirectory, `${slug}.mdx`);
    const fileContents = fs.readFileSync(fullPath, "utf8");

    // Parse the markdown with frontmatter
    const { data, content } = matter(fileContents);
    const frontmatter = data as BlogPostFrontmatter;

    return {
      slug: frontmatter.slug || slug,
      title: frontmatter.title,
      date: frontmatter.date,
      authors: frontmatter.authors,
      category: frontmatter.category,
      image: frontmatter.image,
      content,
      featured: frontmatter.featured,
    };
  } catch (error) {
    console.error(`Error reading blog post ${slug}:`, error);
    return null;
  }
}

/**
 * Get all blog posts sorted by date (newest first)
 */
export async function getAllBlogPosts(
  includeContent: boolean = false,
): Promise<BlogPost[]> {
  const slugs = await getAllBlogSlugs();
  const posts = await Promise.all(
    slugs.map(async (slug) => {
      const post = await getBlogPost(slug);
      if (!post) return null;

      // Optionally exclude content for better performance
      if (!includeContent) {
        return { ...post, content: "" };
      }

      return post;
    }),
  );

  return posts
    .filter((post): post is BlogPost => post !== null)
    .sort((a, b) => {
      // Featured posts come first
      if (a.featured && !b.featured) return -1;
      if (!a.featured && b.featured) return 1;

      // Then sort by date, newest first
      return new Date(b.date).getTime() - new Date(a.date).getTime();
    });
}
