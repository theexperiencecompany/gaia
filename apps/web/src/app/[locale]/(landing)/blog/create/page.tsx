import type { Metadata } from "next";

import CreateBlogPage from "@/features/blog/components/CreateBlogPage";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Create Blog Post",
  description: "Create a new blog post for GAIA",
  path: "/blog/create",
  noIndex: true,
});

export default function BlogCreatePage() {
  return <CreateBlogPage />;
}
