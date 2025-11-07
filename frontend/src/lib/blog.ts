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
}

export interface BlogPostFrontmatter {
  title: string;
  date: string;
  authors: Author[];
  category: string;
  image: string;
  slug: string;
}

/**
 * Get all blog post slugs
 */
export function getAllBlogSlugs(): string[] {
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
export function getBlogPost(slug: string): BlogPost | null {
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
    };
  } catch (error) {
    console.error(`Error reading blog post ${slug}:`, error);
    return null;
  }
}

/**
 * Get all blog posts sorted by date (newest first)
 */
export function getAllBlogPosts(includeContent: boolean = false): BlogPost[] {
  const slugs = getAllBlogSlugs();
  const posts = slugs
    .map((slug) => {
      const post = getBlogPost(slug);
      if (!post) return null;

      // Optionally exclude content for better performance
      if (!includeContent) {
        return { ...post, content: "" };
      }

      return post;
    })
    .filter((post): post is BlogPost => post !== null)
    .sort((a, b) => {
      // Sort by date, newest first
      return new Date(b.date).getTime() - new Date(a.date).getTime();
    });

  return posts;
}
