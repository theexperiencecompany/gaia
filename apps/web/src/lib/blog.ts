import fs from "fs";
import matter from "gray-matter";
import path from "path";
import { cache } from "react";
import type { BlogPost, BlogPostFrontmatter } from "./blog.types";

export type {
  Author,
  BlogPost,
  BlogPostFrontmatter,
  BlogPostMeta,
} from "./blog.types";

const postsDirectory = path.join(process.cwd(), "content/blog");

/**
 * Get all blog post slugs
 */
export const getAllBlogSlugs = cache(async (): Promise<string[]> => {
  try {
    const files = fs.readdirSync(postsDirectory);
    return files.flatMap((file) => {
      if (!file.endsWith(".mdx") && !file.endsWith(".md")) return [];
      const slug = file.replace(/\.(mdx|md)$/, "");
      if (slug === "README" || slug === "TEMPLATE") return [];
      return [slug];
    });
  } catch (error) {
    console.error("Error reading blog directory:", error);
    return [];
  }
});

/**
 * Get a single blog post by slug
 */
export const getBlogPost = cache(
  async (slug: string): Promise<BlogPost | null> => {
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
  },
);

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
    .toSorted((a, b) => {
      // Featured posts come first
      if (a.featured && !b.featured) return -1;
      if (!a.featured && b.featured) return 1;

      // Then sort by date, newest first
      return new Date(b.date).getTime() - new Date(a.date).getTime();
    });
}
