# Blog Content Directory

This directory contains all blog posts as MDX/Markdown files.

## Adding a New Blog Post

1. Create a new `.mdx` file in this directory (e.g., `my-new-post.mdx`)
2. Add frontmatter at the top of the file:

```mdx
---
title: "Your Blog Post Title"
date: "2025-11-02"
authors:
  - name: "Aryan"
    role: "Founder & CEO"
    avatar: "https://github.com/aryanranderiya.png"
    linkedin: "https://linkedin.com/in/aryanranderiya"
    twitter: "https://twitter.com/aryanranderiya"
    github: "https://github.com/aryanranderiya"
category: "Product"
image: "/images/blog/your-image.webp"
slug: "your-url-slug"
---

# Your Blog Post Content

Write your blog post content here using Markdown syntax.

## Subheading

- Bullet points
- **Bold text**
- _Italic text_
- [Links](https://example.com)
```

3. The file will automatically be picked up and displayed on the blog page

## Frontmatter Fields

- **title** (required): The title of your blog post
- **date** (required): Publication date in YYYY-MM-DD format
- **authors** (required): Array of author objects with name, role, and avatar
- **category** (required): Blog post category (e.g., "Product", "Engineering", "AI", etc.)
- **image** (required): Featured image path (relative to public directory)
- **slug** (required): URL-friendly slug for the blog post

## Markdown Features

You can use all standard Markdown features:

- Headings (# H1, ## H2, etc.)
- Bold, italic, strikethrough
- Lists (ordered and unordered)
- Links and images
- Code blocks with syntax highlighting
- Blockquotes
- Tables

## Custom Components

You can also use React components in your MDX files if needed.
