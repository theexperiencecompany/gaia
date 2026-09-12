import type { Schema } from "@shared/api/generated";
import { api } from "@/lib/api/client";

export type BlogPost = Schema<"BlogPost">;

export const blogApi = {
  getBlogs: async (includeContent: boolean = false): Promise<BlogPost[]> => {
    const response = await api.get<BlogPost[]>(
      `/blogs?include_content=${includeContent}`,
    );
    return response.data;
  },

  getBlog: async (slug: string): Promise<BlogPost> => {
    const response = await api.get<BlogPost>(`/blogs/${slug}`);
    return response.data;
  },

  createBlogWithFormData: async (formData: FormData): Promise<BlogPost> => {
    // Posts to the same-origin route handler, which attaches the server-only
    // write credential. The token is never exposed to the browser.
    const response = await fetch("/api/blog", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Failed to create blog post (${response.status})`);
    }

    return (await response.json()) as BlogPost;
  },
};
