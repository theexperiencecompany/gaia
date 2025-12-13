import axios from "axios";

import { api } from "@/lib/api";

export interface TeamMember {
  id: string;
  name: string;
  role: string;
  avatar?: string;
  linkedin?: string;
  twitter?: string;
}

export interface BlogPost {
  id: string;
  slug: string;
  title: string;
  date: string;
  authors: string[];
  author_details?: TeamMember[];
  category: string;
  content: string;
  image?: string;
}

export interface BlogPostCreate {
  slug: string;
  title: string;
  date: string;
  authors: string[];
  category: string;
  content: string;
  image?: string;
}

export interface BlogPostUpdate {
  title?: string;
  date?: string;
  authors?: string[];
  category?: string;
  content?: string;
  image?: string;
}

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

  createBlogWithFormData: async (
    formData: FormData,
    bearerToken: string,
  ): Promise<BlogPost> => {
    const response = await axios.post<BlogPost>(
      `${process.env.NEXT_PUBLIC_API_BASE_URL}blogs`,
      formData,
      {
        headers: {
          Authorization: `Bearer ${bearerToken}`,
          "Content-Type": "multipart/form-data",
        },
      },
    );
    return response.data;
  },
};
