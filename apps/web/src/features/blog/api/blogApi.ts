import type { BlogPost } from "@shared/api/generated";

export type { BlogPost } from "@shared/api/generated";

import { api } from "@/lib/api/typed";

export const blogApi = {
  getBlogs: (includeContent: boolean = false) =>
    api.get("/api/v1/blogs", { query: { include_content: includeContent } }),

  getBlog: (slug: string) =>
    api.get("/api/v1/blogs/{slug}", { path: { slug } }),

  createBlogWithFormData: async (formData: FormData): Promise<BlogPost> => {
    // Posts to the same-origin route handler, which attaches the server-only
    // write credential. The token is never exposed to the browser, so this is
    // the app's own route rather than an API path the schema describes.
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
