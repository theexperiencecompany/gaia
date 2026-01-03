import { Button, Card } from "heroui-native";
import { Linking, Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";

export interface EmailSentData {
  to: string[];
  subject: string;
  message_id?: string;
  sent_at?: string;
}

export function EmailSentCard({ data }: { data: EmailSentData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Email Sent</Text>
        <Text className="text-foreground font-medium mb-1">
          {data.subject || "No Subject"}
        </Text>
        <Text className="text-muted text-sm">To: {data.to?.join(", ")}</Text>
      </Card.Body>
    </Card>
  );
}

export interface EmailThreadData {
  thread_id?: string;
  subject?: string;
  messages?: Array<{
    from?: string;
    snippet?: string;
    date?: string;
  }>;
}

export function EmailThreadCard({ data }: { data: EmailThreadData }) {
  const messageCount = data.messages?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Email Thread</Text>
        <Text className="text-foreground font-medium mb-1">
          {data.subject || "No Subject"}
        </Text>
        <Text className="text-muted text-sm">
          {messageCount} message{messageCount !== 1 ? "s" : ""}
        </Text>
      </Card.Body>
    </Card>
  );
}

export interface EmailFetchItem {
  from?: string;
  subject?: string;
  snippet?: string;
  date?: string;
}

export function EmailFetchCard({ data }: { data: EmailFetchItem[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">Emails ({data.length})</Text>
        {data.slice(0, 3).map((email, index) => (
          <View
            key={`email-${email.subject || index}`}
            className="mb-2 last:mb-0"
          >
            <Text className="text-foreground text-sm" numberOfLines={1}>
              {email.subject || "No Subject"}
            </Text>
            <Text className="text-muted text-xs" numberOfLines={1}>
              {email.from}
            </Text>
          </View>
        ))}
        {data.length > 3 && (
          <Text className="text-muted text-xs">
            +{data.length - 3} more emails
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export interface CalendarOption {
  title?: string;
  start?: string;
  end?: string;
  location?: string;
  description?: string;
}

export function CalendarOptionsCard({ data }: { data: CalendarOption[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">
          Calendar Events ({data.length})
        </Text>
        {data.slice(0, 3).map((event, index) => (
          <View
            key={`event-${event.title || index}`}
            className="mb-2 last:mb-0"
          >
            <Text className="text-foreground text-sm font-medium">
              {event.title || "Untitled Event"}
            </Text>
            {event.start && (
              <Text className="text-muted text-xs">
                {new Date(event.start).toLocaleString()}
              </Text>
            )}
          </View>
        ))}
        {data.length > 3 && (
          <Text className="text-muted text-xs">
            +{data.length - 3} more events
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export interface CalendarFetchItem {
  summary?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
}

export function CalendarFetchCard({ data }: { data: CalendarFetchItem[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">
          Fetched Events ({data.length})
        </Text>
        {data.slice(0, 3).map((event, index) => (
          <View
            key={`fetch-${event.summary || index}`}
            className="mb-2 last:mb-0"
          >
            <Text className="text-foreground text-sm">
              {event.summary || "Untitled Event"}
            </Text>
            <Text className="text-muted text-xs">
              {event.start?.dateTime || event.start?.date || "No date"}
            </Text>
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}

export interface CalendarDeleteOption {
  event_id?: string;
  title?: string;
}

export function CalendarDeleteCard({ data }: { data: CalendarDeleteOption[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Delete Events</Text>
        <Text className="text-foreground text-sm">
          {data.length} event{data.length !== 1 ? "s" : ""} to delete
        </Text>
      </Card.Body>
    </Card>
  );
}

export interface CalendarEditOption {
  event_id?: string;
  title?: string;
  changes?: Record<string, unknown>;
}

export function CalendarEditCard({ data }: { data: CalendarEditOption[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Edit Events</Text>
        <Text className="text-foreground text-sm">
          {data.length} event{data.length !== 1 ? "s" : ""} to edit
        </Text>
      </Card.Body>
    </Card>
  );
}

export interface WeatherData {
  location?: string;
  temperature?: number;
  condition?: string;
  humidity?: number;
  wind_speed?: number;
  unit?: string;
}

export function WeatherCard({ data }: { data: WeatherData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Weather</Text>
        <Text className="text-foreground font-medium text-lg">
          {data.location || "Unknown Location"}
        </Text>
        {data.temperature !== undefined && (
          <Text className="text-foreground text-2xl font-bold">
            {data.temperature}°{data.unit || "C"}
          </Text>
        )}
        {data.condition && (
          <Text className="text-muted text-sm">{data.condition}</Text>
        )}
        {data.humidity !== undefined && (
          <Text className="text-muted text-xs">Humidity: {data.humidity}%</Text>
        )}
      </Card.Body>
    </Card>
  );
}

export interface WebResult {
  title?: string;
  url?: string;
  snippet?: string;
}

export interface SearchResults {
  web?: WebResult[];
  images?: Array<{ url?: string }>;
  news?: Array<{ title?: string }>;
  query?: string;
}

export function SearchResultsCard({ data }: { data: SearchResults }) {
  const webCount = data.web?.length || 0;
  const imageCount = data.images?.length || 0;
  const newsCount = data.news?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Search Results</Text>
        {data.query && (
          <Text className="text-foreground font-medium mb-2">
            "{data.query}"
          </Text>
        )}
        <View className="flex-row gap-3">
          {webCount > 0 && (
            <Text className="text-muted text-sm">{webCount} web</Text>
          )}
          {imageCount > 0 && (
            <Text className="text-muted text-sm">{imageCount} images</Text>
          )}
          {newsCount > 0 && (
            <Text className="text-muted text-sm">{newsCount} news</Text>
          )}
        </View>
        {data.web && data.web.length > 0 && (
          <View className="mt-2">
            {data.web.slice(0, 2).map((result) => (
              <Pressable
                key={result.url || result.title}
                onPress={() => result.url && Linking.openURL(result.url)}
                className="mb-2"
              >
                <Text className="text-primary text-sm" numberOfLines={1}>
                  {result.title}
                </Text>
              </Pressable>
            ))}
          </View>
        )}
      </Card.Body>
    </Card>
  );
}

export interface DeepResearchResults {
  topic?: string;
  summary?: string;
  sources?: Array<{ title?: string; url?: string }>;
}

export function DeepResearchCard({ data }: { data: DeepResearchResults }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Deep Research</Text>
        {data.topic && (
          <Text className="text-foreground font-medium mb-1">{data.topic}</Text>
        )}
        {data.summary && (
          <Text className="text-muted text-sm" numberOfLines={3}>
            {data.summary}
          </Text>
        )}
        {data.sources && data.sources.length > 0 && (
          <Text className="text-muted text-xs mt-2">
            {data.sources.length} sources
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export interface ContactData {
  name?: string;
  email?: string;
  phone?: string;
}

export function ContactListCard({ data }: { data: ContactData[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">
          Contacts ({data.length})
        </Text>
        {data.slice(0, 3).map((contact) => (
          <View key={contact.email || contact.name} className="mb-2 last:mb-0">
            <Text className="text-foreground text-sm">
              {contact.name || contact.email || "Unknown"}
            </Text>
            {contact.email && (
              <Text className="text-muted text-xs">{contact.email}</Text>
            )}
          </View>
        ))}
        {data.length > 3 && (
          <Text className="text-muted text-xs">+{data.length - 3} more</Text>
        )}
      </Card.Body>
    </Card>
  );
}

export interface PeopleSearchData {
  name?: string;
  email?: string;
  organization?: string;
}

export function PeopleSearchCard({ data }: { data: PeopleSearchData[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">
          People Search ({data.length})
        </Text>
        {data.slice(0, 3).map((person) => (
          <View key={person.email || person.name} className="mb-2 last:mb-0">
            <Text className="text-foreground text-sm">
              {person.name || "Unknown"}
            </Text>
            {person.organization && (
              <Text className="text-muted text-xs">{person.organization}</Text>
            )}
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}

export interface SupportTicketData {
  type?: string;
  title?: string;
  description?: string;
}

export function SupportTicketCard({ data }: { data: SupportTicketData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">
          {data.type === "feature" ? "Feature Request" : "Support Ticket"}
        </Text>
        <Text className="text-foreground font-medium mb-1">
          {data.title || "No Title"}
        </Text>
        {data.description && (
          <Text className="text-muted text-sm" numberOfLines={2}>
            {data.description}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export interface NotificationData {
  notifications?: Array<{
    title?: string;
    body?: string;
    type?: string;
  }>;
}

export function NotificationCard({ data }: { data: NotificationData }) {
  const count = data.notifications?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Notifications</Text>
        <Text className="text-foreground text-sm">
          {count} notification{count !== 1 ? "s" : ""}
        </Text>
        {data.notifications?.slice(0, 2).map((notif) => (
          <Text
            key={notif.title || notif.body}
            className="text-muted text-xs mt-1"
            numberOfLines={1}
          >
            • {notif.title || notif.body}
          </Text>
        ))}
      </Card.Body>
    </Card>
  );
}

export interface TodoData {
  todos?: Array<{
    title?: string;
    completed?: boolean;
  }>;
  action?: string;
  message?: string;
}

export function TodoCard({ data }: { data: TodoData }) {
  const todoCount = data.todos?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Todos</Text>
        {data.message && (
          <Text className="text-foreground text-sm mb-1">{data.message}</Text>
        )}
        {data.todos && todoCount > 0 && (
          <>
            {data.todos.slice(0, 3).map((todo) => (
              <Text
                key={todo.title}
                className={`text-sm ${todo.completed ? "text-muted line-through" : "text-foreground"}`}
              >
                • {todo.title}
              </Text>
            ))}
            {todoCount > 3 && (
              <Text className="text-muted text-xs mt-1">
                +{todoCount - 3} more
              </Text>
            )}
          </>
        )}
      </Card.Body>
    </Card>
  );
}

export interface GoalData {
  goals?: Array<{
    title?: string;
    status?: string;
    progress?: number;
  }>;
  action?: string;
  message?: string;
}

export function GoalCard({ data }: { data: GoalData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Goals</Text>
        {data.message && (
          <Text className="text-foreground text-sm mb-1">{data.message}</Text>
        )}
        {data.goals?.slice(0, 2).map((goal) => (
          <View key={goal.title} className="mb-1">
            <Text className="text-foreground text-sm">{goal.title}</Text>
            {goal.progress !== undefined && (
              <Text className="text-muted text-xs">{goal.progress}%</Text>
            )}
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}

export interface DocumentData {
  title?: string;
  content?: string;
  type?: string;
}

export function DocumentCard({ data }: { data: DocumentData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">
          {data.type || "Document"}
        </Text>
        <Text className="text-foreground font-medium">
          {data.title || "Untitled Document"}
        </Text>
        {data.content && (
          <Text className="text-muted text-sm mt-1" numberOfLines={2}>
            {data.content}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export interface GoogleDocsData {
  documentId?: string;
  title?: string;
  url?: string;
}

export function GoogleDocsCard({ data }: { data: GoogleDocsData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Google Doc</Text>
        <Text className="text-foreground font-medium">
          {data.title || "Untitled Document"}
        </Text>
        {data.url && (
          <Pressable onPress={() => Linking.openURL(data.url!)}>
            <Text className="text-primary text-sm mt-1">Open in Browser</Text>
          </Pressable>
        )}
      </Card.Body>
    </Card>
  );
}

export interface CodeData {
  language?: string;
  code?: string;
  output?: string;
  error?: string;
}

export function CodeExecutionCard({ data }: { data: CodeData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">
          Code {data.language ? `(${data.language})` : ""}
        </Text>
        {data.output && (
          <Text className="text-foreground text-sm font-mono" numberOfLines={5}>
            {data.output}
          </Text>
        )}
        {data.error && (
          <Text className="text-danger text-sm font-mono" numberOfLines={3}>
            {data.error}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export interface IntegrationConnectionData {
  integration_name?: string;
  message?: string;
  connect_url?: string;
}

export function IntegrationConnectionCard({
  data,
}: {
  data: IntegrationConnectionData;
}) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Connection Required</Text>
        <Text className="text-foreground font-medium">
          {data.integration_name || "Integration"}
        </Text>
        {data.message && (
          <Text className="text-muted text-sm mt-1">{data.message}</Text>
        )}
        {data.connect_url && (
          <Button
            variant="primary"
            size="sm"
            className="mt-2"
            onPress={() => Linking.openURL(data.connect_url!)}
          >
            <Button.Label>Connect</Button.Label>
          </Button>
        )}
      </Card.Body>
    </Card>
  );
}

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
