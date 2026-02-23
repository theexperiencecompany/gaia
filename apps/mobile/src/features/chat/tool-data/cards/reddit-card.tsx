import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface RedditData {
  type?: "search" | "post" | "comments" | "post_created" | "comment_created";
  posts?: Array<{ title?: string; subreddit?: string }>;
  post?: { title?: string; subreddit?: string };
  comments?: Array<{ body?: string }>;
  data?: { url?: string };
}

export function RedditCard({ data }: { data: RedditData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Reddit</Text>
        {data.type === "search" && data.posts && (
          <>
            <Text className="text-foreground text-sm">
              {data.posts.length} posts found
            </Text>
            {data.posts.slice(0, 2).map((post) => (
              <Text
                key={post.title}
                className="text-muted text-xs mt-1"
                numberOfLines={1}
              >
                • {post.title}
              </Text>
            ))}
          </>
        )}
        {data.type === "post" && data.post && (
          <Text className="text-foreground text-sm">{data.post.title}</Text>
        )}
        {data.type === "comments" && data.comments && (
          <Text className="text-foreground text-sm">
            {data.comments.length} comments
          </Text>
        )}
        {(data.type === "post_created" || data.type === "comment_created") && (
          <Text className="text-foreground text-sm">
            {data.type === "post_created" ? "Post created" : "Comment created"}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}
