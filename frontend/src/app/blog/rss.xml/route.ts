import { blogApi } from "@/features/blog/api/blogApi";

export async function GET() {
  try {
    const blogs = await blogApi.getBlogs(true);
    const baseUrl = "https://heygaia.io";

    const rssItems = blogs
      .map((blog) => {
        const pubDate = new Date(blog.date).toUTCString();
        const link = `${baseUrl}/blog/${blog.slug}`;
        const authors =
          blog.author_details?.map((author) => author.name).join(", ") ||
          blog.authors.join(", ");

        // Clean content for RSS (strip HTML, limit length)
        const description =
          blog.content
            .replace(/[#*`\[\]()]/g, "")
            .replace(/\n/g, " ")
            .slice(0, 500)
            .trim() + "...";

        return `
    <item>
      <title><![CDATA[${blog.title}]]></title>
      <link>${link}</link>
      <guid isPermaLink="true">${link}</guid>
      <description><![CDATA[${description}]]></description>
      <pubDate>${pubDate}</pubDate>
      <author><![CDATA[${authors}]]></author>
      <category>${blog.category}</category>
      ${blog.image ? `<enclosure url="${blog.image}" type="image/webp"/>` : ""}
    </item>`;
      })
      .join("");

    const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>GAIA Blog</title>
    <link>${baseUrl}/blog</link>
    <description>Read the latest updates, insights, and stories from the GAIA team. Learn about AI, productivity, open-source development, and our journey building the future of personal AI assistants.</description>
    <language>en-us</language>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
    <atom:link href="${baseUrl}/blog/rss.xml" rel="self" type="application/rss+xml"/>
    <image>
      <url>${baseUrl}/images/logos/logo.webp</url>
      <title>GAIA Blog</title>
      <link>${baseUrl}/blog</link>
    </image>
    ${rssItems}
  </channel>
</rss>`;

    return new Response(rss, {
      headers: {
        "Content-Type": "application/xml; charset=utf-8",
        "Cache-Control": "public, max-age=3600, s-maxage=3600",
      },
    });
  } catch (error) {
    console.error("Error generating RSS feed:", error);
    return new Response("Error generating RSS feed", { status: 500 });
  }
}
