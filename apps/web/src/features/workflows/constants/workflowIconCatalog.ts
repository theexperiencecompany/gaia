import {
  AbacusIcon,
  AiBrain01Icon,
  AiMagicIcon,
  Airplane01Icon,
  AlarmClockIcon,
  AnalyticsUpIcon,
  ApiIcon,
  AppleIcon,
  ArchiveIcon,
  ArtboardIcon,
  Award01Icon,
  BackpackIcon,
  BankIcon,
  BeachIcon,
  BedIcon,
  BirthdayCakeIcon,
  Bitcoin01Icon,
  Book01Icon,
  Book02Icon,
  BookmarkIcon,
  Briefcase01Icon,
  Bug01Icon,
  Building01Icon,
  Bus01Icon,
  Calculator01Icon,
  Calendar01Icon,
  Calendar03Icon,
  CalendarAdd01Icon,
  Call02Icon,
  CallIncoming02Icon,
  Camera01Icon,
  Car01Icon,
  Certificate01Icon,
  ChampionIcon,
  Chart01Icon,
  ChartBarLineIcon,
  ChartUpIcon,
  Chat01Icon,
  ChatBotIcon,
  CheckListIcon,
  CheckmarkCircle01Icon,
  ChefHatIcon,
  ChessIcon,
  ClipboardIcon,
  Clock01Icon,
  CloudIcon,
  Coffee01Icon,
  Coins01Icon,
  CommandIcon,
  CommentAdd01Icon,
  Compass01Icon,
  ComputerTerminal01Icon,
  Contact01Icon,
  CreditCardIcon,
  CrownIcon,
  Database01Icon,
  DiamondIcon,
  DiceIcon,
  DiscordIcon,
  DollarCircleIcon,
  Dumbbell01Icon,
  Dumbbell02Icon,
  Film01Icon,
  FingerPrintIcon,
  FireIcon,
  Flag01Icon,
  FlashIcon,
  FlowerIcon,
  FolderIcon,
  GameController01Icon,
  GiftIcon,
  GitBranchIcon,
  GitCommitIcon,
  GlobeIcon,
  GraduationScrollIcon,
  HeadphonesIcon,
  HeartAddIcon,
  HeartCheckIcon,
  Home01Icon,
  HourglassIcon,
  IceCreamIcon,
  type IconProps,
  Idea01Icon,
  Image01Icon,
  InboxIcon,
  Invoice01Icon,
  JoystickIcon,
  Key01Icon,
  Layers01Icon,
  Leaf01Icon,
  LinkSquare01Icon,
  ListViewIcon,
  Location01Icon,
  LockIcon,
  Luggage01Icon,
  MagicWand01Icon,
  Mail01Icon,
  MailSend01Icon,
  MapsIcon,
  Medicine01Icon,
  MedicineBottle01Icon,
  Megaphone01Icon,
  Message01Icon,
  Mic01Icon,
  Money01Icon,
  MoneyBag01Icon,
  Moon01Icon,
  MountainIcon,
  MusicNote01Icon,
  Note01Icon,
  Notebook01Icon,
  NotificationIcon,
  Package01Icon,
  PartyIcon,
  Passport01Icon,
  Pen01Icon,
  PencilEdit01Icon,
  PiggyBankIcon,
  PinLocation01Icon,
  Pizza01Icon,
  PlugSocketIcon,
  PodcastIcon,
  PresentationIcon,
  PuzzleIcon,
  RainIcon,
  ReceiptDollarIcon,
  Restaurant01Icon,
  Robot01Icon,
  Rocket01Icon,
  RulerIcon,
  RunningShoesIcon,
  SafeIcon,
  SchoolIcon,
  SecurityIcon,
  SendingOrderIcon,
  Settings01Icon,
  Share01Icon,
  Shield01Icon,
  ShoppingBag01Icon,
  ShoppingCart01Icon,
  SlackIcon,
  SleepingIcon,
  SmartPhone01Icon,
  SmileIcon,
  SofaIcon,
  SourceCodeIcon,
  SparklesIcon,
  StarIcon,
  StickyNote01Icon,
  StopWatchIcon,
  StudyLampIcon,
  Sun01Icon,
  Target01Icon,
  Task01Icon,
  TaskDone01Icon,
  TelegramIcon,
  Telescope01Icon,
  TestTube01Icon,
  ThumbsUpIcon,
  Ticket01Icon,
  Time04Icon,
  Timer01Icon,
  TimeScheduleIcon,
  Train01Icon,
  TreeIcon,
  Tv01Icon,
  UserAdd01Icon,
  UserGroupIcon,
  UserIcon,
  VacuumCleanerIcon,
  Video01Icon,
  Video02Icon,
  Wallet01Icon,
  Watch01Icon,
  WhatsappIcon,
  WifiIcon,
  Wrench01Icon,
  Yoga01Icon,
  ZapIcon,
} from "@icons";
import type { ComponentType } from "react";

export interface WorkflowIconDef {
  /** Stored slug — the gaia-icons component export name */
  name: string;
  Icon: ComponentType<IconProps>;
  keywords: string[];
}

/** Preset swatches for the workflow icon (dark-UI friendly, tailwind-400-ish) */
/**
 * Vibrant swatches computed in OKLCH (uniform lightness/chroma, evenly spaced
 * hues, gamut-mapped to sRGB) so every color reads equally bright on dark UI.
 */
export const WORKFLOW_ICON_COLORS = [
  "#ff726b", // coral
  "#f68001", // orange
  "#eebe0c", // gold
  "#5fbf49", // green
  "#0ebfa0", // teal
  "#09b7dc", // cyan
  "#72a3fe", // blue
  "#ad8dfe", // violet
  "#e175d9", // magenta
  "#fb6ca0", // pink
] as const;

export const DEFAULT_WORKFLOW_ICON_COLOR = WORKFLOW_ICON_COLORS[6]; // blue

/** Alpha suffix appended to a swatch hex for the icon's tinted background. */
export const WORKFLOW_ICON_BG_ALPHA = "26"; // ~15%

/** Popular automation icons surfaced as suggestions when the picker query is empty. */
export const WORKFLOW_SUGGESTED_ICONS = [
  "AlarmClockIcon", // reminders
  "Mail01Icon", // email automations
  "Calendar01Icon", // scheduling
  "CheckListIcon", // todos / tasks
  "ZapIcon", // generic automation
  "AiMagicIcon", // AI assist
  "NotificationIcon", // nudges / alerts
  "SourceCodeIcon", // dev workflows
  "Dumbbell01Icon", // habits / fitness
  "MoneyBag01Icon", // finance check-ins
  "Book01Icon", // study / reading
  "GlobeIcon", // news / web digests
] as const;

export const WORKFLOW_ICON_CATALOG: WorkflowIconDef[] = [
  // Communication
  {
    name: "Mail01Icon",
    Icon: Mail01Icon,
    keywords: ["email", "inbox", "gmail", "newsletter"],
  },
  { name: "InboxIcon", Icon: InboxIcon, keywords: ["email", "mail", "unread"] },
  {
    name: "MailSend01Icon",
    Icon: MailSend01Icon,
    keywords: ["email", "outbox", "send", "compose"],
  },
  {
    name: "Message01Icon",
    Icon: Message01Icon,
    keywords: ["sms", "text", "chat", "dm"],
  },
  {
    name: "Chat01Icon",
    Icon: Chat01Icon,
    keywords: ["conversation", "message", "bubble", "dm"],
  },
  {
    name: "ChatBotIcon",
    Icon: ChatBotIcon,
    keywords: ["assistant", "ai", "support", "conversation"],
  },
  {
    name: "Call02Icon",
    Icon: Call02Icon,
    keywords: ["phone", "voice", "dial", "telephone"],
  },
  {
    name: "CallIncoming02Icon",
    Icon: CallIncoming02Icon,
    keywords: ["phone", "ringing", "answer", "voice"],
  },
  {
    name: "Video01Icon",
    Icon: Video01Icon,
    keywords: ["call", "zoom", "meeting", "conference"],
  },
  {
    name: "SmartPhone01Icon",
    Icon: SmartPhone01Icon,
    keywords: ["mobile", "cell", "device", "text"],
  },
  {
    name: "Megaphone01Icon",
    Icon: Megaphone01Icon,
    keywords: ["announcement", "broadcast", "alert", "promote"],
  },
  {
    name: "NotificationIcon",
    Icon: NotificationIcon,
    keywords: ["alert", "bell", "reminder", "ping"],
  },
  {
    name: "SendingOrderIcon",
    Icon: SendingOrderIcon,
    keywords: ["send", "submit", "dispatch", "paper plane"],
  },
  {
    name: "CommentAdd01Icon",
    Icon: CommentAdd01Icon,
    keywords: ["comment", "reply", "feedback", "note"],
  },
  {
    name: "WhatsappIcon",
    Icon: WhatsappIcon,
    keywords: ["whatsapp", "messaging", "chat"],
  },
  {
    name: "TelegramIcon",
    Icon: TelegramIcon,
    keywords: ["telegram", "messaging", "chat", "bot"],
  },
  {
    name: "SlackIcon",
    Icon: SlackIcon,
    keywords: ["slack", "team chat", "workspace"],
  },
  {
    name: "DiscordIcon",
    Icon: DiscordIcon,
    keywords: ["discord", "community", "server", "chat"],
  },
  {
    name: "Contact01Icon",
    Icon: Contact01Icon,
    keywords: ["contact", "address book", "person", "crm"],
  },

  // Time / scheduling
  {
    name: "Calendar01Icon",
    Icon: Calendar01Icon,
    keywords: ["schedule", "date", "event", "planner"],
  },
  {
    name: "Calendar03Icon",
    Icon: Calendar03Icon,
    keywords: ["schedule", "date", "event", "agenda"],
  },
  {
    name: "CalendarAdd01Icon",
    Icon: CalendarAdd01Icon,
    keywords: ["schedule", "new event", "booking", "plan"],
  },
  {
    name: "Clock01Icon",
    Icon: Clock01Icon,
    keywords: ["time", "hour", "schedule", "duration"],
  },
  {
    name: "AlarmClockIcon",
    Icon: AlarmClockIcon,
    keywords: ["wake up", "reminder", "alert", "morning"],
  },
  {
    name: "Timer01Icon",
    Icon: Timer01Icon,
    keywords: ["countdown", "stopwatch", "duration", "pomodoro"],
  },
  {
    name: "StopWatchIcon",
    Icon: StopWatchIcon,
    keywords: ["timer", "duration", "race", "speed"],
  },
  {
    name: "HourglassIcon",
    Icon: HourglassIcon,
    keywords: ["waiting", "time", "pending", "sand timer"],
  },
  {
    name: "TimeScheduleIcon",
    Icon: TimeScheduleIcon,
    keywords: ["calendar", "planner", "agenda", "booking"],
  },
  {
    name: "Watch01Icon",
    Icon: Watch01Icon,
    keywords: ["time", "wristwatch", "wearable", "clock"],
  },
  {
    name: "Time04Icon",
    Icon: Time04Icon,
    keywords: ["clock", "duration", "deadline", "schedule"],
  },

  // Productivity
  {
    name: "Task01Icon",
    Icon: Task01Icon,
    keywords: ["todo", "checklist", "action item"],
  },
  {
    name: "TaskDone01Icon",
    Icon: TaskDone01Icon,
    keywords: ["complete", "checked", "finished", "todo"],
  },
  {
    name: "CheckListIcon",
    Icon: CheckListIcon,
    keywords: ["todo", "list", "tasks", "agenda"],
  },
  {
    name: "CheckmarkCircle01Icon",
    Icon: CheckmarkCircle01Icon,
    keywords: ["done", "approved", "success", "verified"],
  },
  {
    name: "Note01Icon",
    Icon: Note01Icon,
    keywords: ["memo", "notes", "writing", "journal"],
  },
  {
    name: "StickyNote01Icon",
    Icon: StickyNote01Icon,
    keywords: ["reminder", "memo", "post-it", "notes"],
  },
  {
    name: "Notebook01Icon",
    Icon: Notebook01Icon,
    keywords: ["journal", "diary", "notes", "log"],
  },
  {
    name: "Pen01Icon",
    Icon: Pen01Icon,
    keywords: ["write", "edit", "draft", "sign"],
  },
  {
    name: "PencilEdit01Icon",
    Icon: PencilEdit01Icon,
    keywords: ["edit", "draft", "write", "revise"],
  },
  {
    name: "Flag01Icon",
    Icon: Flag01Icon,
    keywords: ["milestone", "goal", "priority", "mark"],
  },
  {
    name: "PinLocation01Icon",
    Icon: PinLocation01Icon,
    keywords: ["pin", "save", "bookmark", "location"],
  },
  {
    name: "ListViewIcon",
    Icon: ListViewIcon,
    keywords: ["list", "items", "outline", "agenda"],
  },
  {
    name: "FolderIcon",
    Icon: FolderIcon,
    keywords: ["files", "directory", "organize", "storage"],
  },
  {
    name: "ArchiveIcon",
    Icon: ArchiveIcon,
    keywords: ["storage", "backup", "old", "records"],
  },
  {
    name: "ClipboardIcon",
    Icon: ClipboardIcon,
    keywords: ["copy", "paste", "checklist", "report"],
  },
  {
    name: "Layers01Icon",
    Icon: Layers01Icon,
    keywords: ["stack", "organize", "grouping", "workflow"],
  },

  // Work / business
  {
    name: "Briefcase01Icon",
    Icon: Briefcase01Icon,
    keywords: ["work", "job", "office", "business"],
  },
  {
    name: "PresentationIcon",
    Icon: PresentationIcon,
    keywords: ["slides", "meeting", "pitch", "deck"],
  },
  {
    name: "ChartUpIcon",
    Icon: ChartUpIcon,
    keywords: ["growth", "analytics", "revenue", "trend"],
  },
  {
    name: "AnalyticsUpIcon",
    Icon: AnalyticsUpIcon,
    keywords: ["metrics", "growth", "reporting", "stats"],
  },
  {
    name: "Target01Icon",
    Icon: Target01Icon,
    keywords: ["goal", "objective", "focus", "kpi"],
  },
  {
    name: "Building01Icon",
    Icon: Building01Icon,
    keywords: ["office", "company", "headquarters", "corporate"],
  },
  {
    name: "ChartBarLineIcon",
    Icon: ChartBarLineIcon,
    keywords: ["analytics", "report", "dashboard", "data"],
  },
  {
    name: "Idea01Icon",
    Icon: Idea01Icon,
    keywords: ["lightbulb", "brainstorm", "innovation", "insight"],
  },
  {
    name: "Chart01Icon",
    Icon: Chart01Icon,
    keywords: ["graph", "data", "report", "dashboard"],
  },

  // Dev / tech
  {
    name: "SourceCodeIcon",
    Icon: SourceCodeIcon,
    keywords: ["code", "programming", "developer", "script"],
  },
  {
    name: "ComputerTerminal01Icon",
    Icon: ComputerTerminal01Icon,
    keywords: ["terminal", "shell", "console", "cli"],
  },
  {
    name: "GitBranchIcon",
    Icon: GitBranchIcon,
    keywords: ["git", "version control", "repo", "merge"],
  },
  {
    name: "GitCommitIcon",
    Icon: GitCommitIcon,
    keywords: ["git", "commit", "version control", "repo"],
  },
  {
    name: "Database01Icon",
    Icon: Database01Icon,
    keywords: ["data", "storage", "sql", "server"],
  },
  {
    name: "CloudIcon",
    Icon: CloudIcon,
    keywords: ["cloud", "storage", "server", "hosting"],
  },
  {
    name: "Bug01Icon",
    Icon: Bug01Icon,
    keywords: ["bug", "error", "debug", "issue"],
  },
  {
    name: "ApiIcon",
    Icon: ApiIcon,
    keywords: ["api", "integration", "endpoint", "webhook"],
  },
  {
    name: "CommandIcon",
    Icon: CommandIcon,
    keywords: ["shortcut", "keyboard", "cli", "hotkey"],
  },
  {
    name: "LinkSquare01Icon",
    Icon: LinkSquare01Icon,
    keywords: ["url", "link", "connect", "integration"],
  },

  // AI / automation
  {
    name: "AiMagicIcon",
    Icon: AiMagicIcon,
    keywords: ["ai", "generate", "smart", "assistant"],
  },
  {
    name: "AiBrain01Icon",
    Icon: AiBrain01Icon,
    keywords: ["ai", "intelligence", "model", "neural"],
  },
  {
    name: "Robot01Icon",
    Icon: Robot01Icon,
    keywords: ["bot", "automation", "ai", "agent"],
  },
  {
    name: "SparklesIcon",
    Icon: SparklesIcon,
    keywords: ["ai", "magic", "generate", "new"],
  },
  {
    name: "MagicWand01Icon",
    Icon: MagicWand01Icon,
    keywords: ["ai", "auto", "magic", "generate"],
  },
  {
    name: "ZapIcon",
    Icon: ZapIcon,
    keywords: ["fast", "instant", "automation", "trigger"],
  },
  {
    name: "FlashIcon",
    Icon: FlashIcon,
    keywords: ["quick", "instant", "power", "trigger"],
  },

  // Finance
  {
    name: "Money01Icon",
    Icon: Money01Icon,
    keywords: ["cash", "finance", "budget", "payment"],
  },
  {
    name: "MoneyBag01Icon",
    Icon: MoneyBag01Icon,
    keywords: ["savings", "cash", "budget", "earnings"],
  },
  {
    name: "Wallet01Icon",
    Icon: Wallet01Icon,
    keywords: ["payment", "budget", "cash", "finance"],
  },
  {
    name: "CreditCardIcon",
    Icon: CreditCardIcon,
    keywords: ["payment", "billing", "card", "subscription"],
  },
  {
    name: "BankIcon",
    Icon: BankIcon,
    keywords: ["finance", "account", "savings", "institution"],
  },
  {
    name: "Invoice01Icon",
    Icon: Invoice01Icon,
    keywords: ["billing", "receipt", "payment", "invoice"],
  },
  {
    name: "DollarCircleIcon",
    Icon: DollarCircleIcon,
    keywords: ["money", "price", "currency", "finance"],
  },
  {
    name: "Coins01Icon",
    Icon: Coins01Icon,
    keywords: ["money", "savings", "currency", "cash"],
  },
  {
    name: "ReceiptDollarIcon",
    Icon: ReceiptDollarIcon,
    keywords: ["expense", "billing", "purchase", "receipt"],
  },
  {
    name: "PiggyBankIcon",
    Icon: PiggyBankIcon,
    keywords: ["savings", "budget", "finance", "money"],
  },
  {
    name: "Bitcoin01Icon",
    Icon: Bitcoin01Icon,
    keywords: ["crypto", "currency", "blockchain", "money"],
  },

  // Health / fitness
  {
    name: "Dumbbell01Icon",
    Icon: Dumbbell01Icon,
    keywords: ["gym", "workout", "fitness", "training"],
  },
  {
    name: "Dumbbell02Icon",
    Icon: Dumbbell02Icon,
    keywords: ["gym", "exercise", "fitness", "strength"],
  },
  {
    name: "HeartCheckIcon",
    Icon: HeartCheckIcon,
    keywords: ["health", "wellness", "checkup", "cardio"],
  },
  {
    name: "HeartAddIcon",
    Icon: HeartAddIcon,
    keywords: ["love", "favorite", "health", "wellness"],
  },
  {
    name: "Medicine01Icon",
    Icon: Medicine01Icon,
    keywords: ["pills", "medication", "health", "pharmacy"],
  },
  {
    name: "MedicineBottle01Icon",
    Icon: MedicineBottle01Icon,
    keywords: ["pills", "prescription", "pharmacy", "health"],
  },
  {
    name: "RunningShoesIcon",
    Icon: RunningShoesIcon,
    keywords: ["run", "jog", "cardio", "exercise"],
  },
  {
    name: "Yoga01Icon",
    Icon: Yoga01Icon,
    keywords: ["meditation", "wellness", "stretch", "mindfulness"],
  },
  {
    name: "SleepingIcon",
    Icon: SleepingIcon,
    keywords: ["sleep", "rest", "bedtime", "nap"],
  },

  // Education
  {
    name: "Book01Icon",
    Icon: Book01Icon,
    keywords: ["read", "study", "learn", "library"],
  },
  {
    name: "Book02Icon",
    Icon: Book02Icon,
    keywords: ["read", "study", "novel", "textbook"],
  },
  {
    name: "GraduationScrollIcon",
    Icon: GraduationScrollIcon,
    keywords: ["diploma", "graduate", "degree", "school"],
  },
  {
    name: "SchoolIcon",
    Icon: SchoolIcon,
    keywords: ["education", "class", "university", "college"],
  },
  {
    name: "Telescope01Icon",
    Icon: Telescope01Icon,
    keywords: ["science", "research", "astronomy", "explore"],
  },
  {
    name: "TestTube01Icon",
    Icon: TestTube01Icon,
    keywords: ["science", "lab", "chemistry", "experiment"],
  },
  {
    name: "BookmarkIcon",
    Icon: BookmarkIcon,
    keywords: ["save", "favorite", "reading", "mark"],
  },
  {
    name: "RulerIcon",
    Icon: RulerIcon,
    keywords: ["measure", "geometry", "school", "design"],
  },
  {
    name: "Calculator01Icon",
    Icon: Calculator01Icon,
    keywords: ["math", "numbers", "finance", "compute"],
  },
  {
    name: "AbacusIcon",
    Icon: AbacusIcon,
    keywords: ["math", "counting", "education", "arithmetic"],
  },
  {
    name: "Certificate01Icon",
    Icon: Certificate01Icon,
    keywords: ["diploma", "award", "credential", "achievement"],
  },
  {
    name: "StudyLampIcon",
    Icon: StudyLampIcon,
    keywords: ["study", "desk", "read", "focus"],
  },

  // Home / errands
  {
    name: "Home01Icon",
    Icon: Home01Icon,
    keywords: ["house", "residence", "chores", "household"],
  },
  {
    name: "ShoppingCart01Icon",
    Icon: ShoppingCart01Icon,
    keywords: ["shopping", "groceries", "checkout", "buy"],
  },
  {
    name: "ShoppingBag01Icon",
    Icon: ShoppingBag01Icon,
    keywords: ["shopping", "retail", "purchase", "store"],
  },
  {
    name: "GiftIcon",
    Icon: GiftIcon,
    keywords: ["present", "birthday", "surprise", "reward"],
  },
  {
    name: "Package01Icon",
    Icon: Package01Icon,
    keywords: ["delivery", "shipping", "parcel", "order"],
  },
  {
    name: "Wrench01Icon",
    Icon: Wrench01Icon,
    keywords: ["repair", "fix", "maintenance", "tools"],
  },
  {
    name: "SofaIcon",
    Icon: SofaIcon,
    keywords: ["furniture", "living room", "home", "couch"],
  },
  {
    name: "BedIcon",
    Icon: BedIcon,
    keywords: ["sleep", "bedroom", "rest", "furniture"],
  },
  {
    name: "PlugSocketIcon",
    Icon: PlugSocketIcon,
    keywords: ["electricity", "power", "outlet", "utility"],
  },
  {
    name: "VacuumCleanerIcon",
    Icon: VacuumCleanerIcon,
    keywords: ["clean", "chores", "housework", "tidy"],
  },

  // Travel
  {
    name: "Airplane01Icon",
    Icon: Airplane01Icon,
    keywords: ["flight", "travel", "trip", "vacation"],
  },
  {
    name: "Car01Icon",
    Icon: Car01Icon,
    keywords: ["drive", "commute", "vehicle", "road trip"],
  },
  {
    name: "MapsIcon",
    Icon: MapsIcon,
    keywords: ["navigation", "directions", "location", "route"],
  },
  {
    name: "Compass01Icon",
    Icon: Compass01Icon,
    keywords: ["navigation", "direction", "explore", "travel"],
  },
  {
    name: "Luggage01Icon",
    Icon: Luggage01Icon,
    keywords: ["travel", "suitcase", "packing", "trip"],
  },
  {
    name: "Passport01Icon",
    Icon: Passport01Icon,
    keywords: ["travel", "id", "visa", "abroad"],
  },
  {
    name: "Ticket01Icon",
    Icon: Ticket01Icon,
    keywords: ["booking", "event", "pass", "reservation"],
  },
  {
    name: "Train01Icon",
    Icon: Train01Icon,
    keywords: ["commute", "railway", "transit", "travel"],
  },
  {
    name: "Bus01Icon",
    Icon: Bus01Icon,
    keywords: ["transit", "commute", "public transport", "travel"],
  },
  {
    name: "BackpackIcon",
    Icon: BackpackIcon,
    keywords: ["travel", "hiking", "school", "packing"],
  },
  {
    name: "BeachIcon",
    Icon: BeachIcon,
    keywords: ["vacation", "summer", "travel", "relax"],
  },

  // Media
  {
    name: "MusicNote01Icon",
    Icon: MusicNote01Icon,
    keywords: ["song", "audio", "playlist", "spotify"],
  },
  {
    name: "Camera01Icon",
    Icon: Camera01Icon,
    keywords: ["photo", "picture", "capture", "photography"],
  },
  {
    name: "Video02Icon",
    Icon: Video02Icon,
    keywords: ["recording", "clip", "movie", "film"],
  },
  {
    name: "Image01Icon",
    Icon: Image01Icon,
    keywords: ["photo", "picture", "gallery", "media"],
  },
  {
    name: "Mic01Icon",
    Icon: Mic01Icon,
    keywords: ["microphone", "voice", "record", "podcast"],
  },
  {
    name: "HeadphonesIcon",
    Icon: HeadphonesIcon,
    keywords: ["audio", "music", "listen", "podcast"],
  },
  {
    name: "Film01Icon",
    Icon: Film01Icon,
    keywords: ["movie", "video", "cinema", "clip"],
  },
  {
    name: "PodcastIcon",
    Icon: PodcastIcon,
    keywords: ["audio", "show", "episode", "broadcast"],
  },
  {
    name: "Tv01Icon",
    Icon: Tv01Icon,
    keywords: ["television", "screen", "watch", "streaming"],
  },

  // Food
  {
    name: "Coffee01Icon",
    Icon: Coffee01Icon,
    keywords: ["drink", "cafe", "espresso", "morning"],
  },
  {
    name: "Restaurant01Icon",
    Icon: Restaurant01Icon,
    keywords: ["dining", "food", "reservation", "eat"],
  },
  {
    name: "Pizza01Icon",
    Icon: Pizza01Icon,
    keywords: ["food", "dinner", "takeout", "delivery"],
  },
  {
    name: "ChefHatIcon",
    Icon: ChefHatIcon,
    keywords: ["cooking", "kitchen", "recipe", "chef"],
  },
  {
    name: "IceCreamIcon",
    Icon: IceCreamIcon,
    keywords: ["dessert", "treat", "snack", "sweet"],
  },
  {
    name: "AppleIcon",
    Icon: AppleIcon,
    keywords: ["fruit", "healthy", "snack", "nutrition"],
  },
  {
    name: "BirthdayCakeIcon",
    Icon: BirthdayCakeIcon,
    keywords: ["celebration", "birthday", "dessert", "party"],
  },

  // Nature / weather
  {
    name: "Sun01Icon",
    Icon: Sun01Icon,
    keywords: ["weather", "sunny", "daytime", "clear"],
  },
  {
    name: "Moon01Icon",
    Icon: Moon01Icon,
    keywords: ["night", "sleep", "dark mode", "evening"],
  },
  {
    name: "RainIcon",
    Icon: RainIcon,
    keywords: ["weather", "storm", "forecast", "wet"],
  },
  {
    name: "Leaf01Icon",
    Icon: Leaf01Icon,
    keywords: ["nature", "plant", "eco", "green"],
  },
  {
    name: "FireIcon",
    Icon: FireIcon,
    keywords: ["streak", "hot", "trending", "flame"],
  },
  {
    name: "StarIcon",
    Icon: StarIcon,
    keywords: ["favorite", "rating", "important", "featured"],
  },
  {
    name: "FlowerIcon",
    Icon: FlowerIcon,
    keywords: ["nature", "garden", "spring", "bloom"],
  },
  {
    name: "MountainIcon",
    Icon: MountainIcon,
    keywords: ["hiking", "outdoors", "nature", "adventure"],
  },
  {
    name: "TreeIcon",
    Icon: TreeIcon,
    keywords: ["nature", "forest", "plant", "outdoors"],
  },

  // Social
  {
    name: "UserIcon",
    Icon: UserIcon,
    keywords: ["person", "profile", "account", "contact"],
  },
  {
    name: "UserGroupIcon",
    Icon: UserGroupIcon,
    keywords: ["team", "people", "community", "group"],
  },
  {
    name: "UserAdd01Icon",
    Icon: UserAdd01Icon,
    keywords: ["invite", "follow", "add contact", "new member"],
  },
  {
    name: "Share01Icon",
    Icon: Share01Icon,
    keywords: ["share", "social", "post", "distribute"],
  },
  {
    name: "ThumbsUpIcon",
    Icon: ThumbsUpIcon,
    keywords: ["like", "approve", "vote", "feedback"],
  },
  {
    name: "SmileIcon",
    Icon: SmileIcon,
    keywords: ["happy", "emoji", "mood", "feedback"],
  },
  {
    name: "Award01Icon",
    Icon: Award01Icon,
    keywords: ["achievement", "recognition", "prize", "medal"],
  },
  {
    name: "ChampionIcon",
    Icon: ChampionIcon,
    keywords: ["trophy", "winner", "achievement", "cup"],
  },

  // Security
  {
    name: "LockIcon",
    Icon: LockIcon,
    keywords: ["security", "private", "password", "secure"],
  },
  {
    name: "Key01Icon",
    Icon: Key01Icon,
    keywords: ["password", "access", "credential", "unlock"],
  },
  {
    name: "Shield01Icon",
    Icon: Shield01Icon,
    keywords: ["protection", "security", "safe", "defense"],
  },
  {
    name: "SafeIcon",
    Icon: SafeIcon,
    keywords: ["security", "vault", "protect", "storage"],
  },
  {
    name: "SecurityIcon",
    Icon: SecurityIcon,
    keywords: ["protection", "safety", "shield", "guard"],
  },
  {
    name: "FingerPrintIcon",
    Icon: FingerPrintIcon,
    keywords: ["biometric", "identity", "authentication", "unlock"],
  },

  // Misc / fun
  {
    name: "Rocket01Icon",
    Icon: Rocket01Icon,
    keywords: ["launch", "startup", "boost", "growth"],
  },
  {
    name: "CrownIcon",
    Icon: CrownIcon,
    keywords: ["premium", "vip", "royalty", "king"],
  },
  {
    name: "DiamondIcon",
    Icon: DiamondIcon,
    keywords: ["premium", "gem", "luxury", "valuable"],
  },
  {
    name: "GameController01Icon",
    Icon: GameController01Icon,
    keywords: ["gaming", "play", "entertainment", "controller"],
  },
  {
    name: "ArtboardIcon",
    Icon: ArtboardIcon,
    keywords: ["design", "color", "creative", "art"],
  },
  {
    name: "PuzzleIcon",
    Icon: PuzzleIcon,
    keywords: ["puzzle", "solve", "integration", "piece"],
  },
  {
    name: "GlobeIcon",
    Icon: GlobeIcon,
    keywords: ["world", "global", "internet", "international"],
  },
  {
    name: "Location01Icon",
    Icon: Location01Icon,
    keywords: ["place", "map pin", "address", "gps"],
  },
  {
    name: "WifiIcon",
    Icon: WifiIcon,
    keywords: ["internet", "network", "connectivity", "wireless"],
  },
  {
    name: "Settings01Icon",
    Icon: Settings01Icon,
    keywords: ["gear", "preferences", "config", "options"],
  },
  {
    name: "PartyIcon",
    Icon: PartyIcon,
    keywords: ["celebration", "event", "festive", "fun"],
  },
  {
    name: "DiceIcon",
    Icon: DiceIcon,
    keywords: ["game", "random", "chance", "gamble"],
  },
  {
    name: "ChessIcon",
    Icon: ChessIcon,
    keywords: ["strategy", "game", "board game", "chess"],
  },
  {
    name: "JoystickIcon",
    Icon: JoystickIcon,
    keywords: ["gaming", "arcade", "controller", "play"],
  },
];

export const WORKFLOW_ICON_MAP: ReadonlyMap<string, WorkflowIconDef> = new Map(
  WORKFLOW_ICON_CATALOG.map((def) => [def.name, def]),
);

/** Normalizes an icon export name for matching: strips a trailing "Icon" and digits, lowercases. */
function normalizeIconName(name: string): string {
  return name.replace(/\d*Icon$/, "").toLowerCase();
}

/** "MoneyBag01Icon" -> ["money", "bag"] — the camelCase words of the icon name. */
function iconNameWords(name: string): string[] {
  return name
    .replace(/\d*Icon$/, "")
    .split(/(?=[A-Z])/)
    .map((word) => word.toLowerCase())
    .filter(Boolean);
}

/** Trim a plural/possessive tail so "reminders" matches "reminder". */
function singularize(term: string): string {
  return term.replace(/'s$|s$/, "");
}

/** Human label for an icon slug: "AlarmClockIcon" -> "Alarm Clock". */
export function workflowIconLabel(name: string): string {
  return name
    .replace(/\d*Icon$/, "")
    .split(/(?=[A-Z])/)
    .join(" ")
    .trim();
}

/** Ranked search: exact/prefix name match > name substring > keyword prefix > keyword substring. Every whitespace-separated query term must match; empty query returns the full catalog. */
export function searchWorkflowIcons(query: string): WorkflowIconDef[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) {
    return WORKFLOW_ICON_CATALOG;
  }

  const scored: { def: WorkflowIconDef; score: number }[] = [];

  for (const def of WORKFLOW_ICON_CATALOG) {
    const normalizedName = normalizeIconName(def.name);
    const nameWords = iconNameWords(def.name);
    let total = 0;
    let matchesAllTerms = true;

    for (const rawTerm of terms) {
      const variants =
        singularize(rawTerm) === rawTerm
          ? [rawTerm]
          : [rawTerm, singularize(rawTerm)];
      let termScore = 0;
      for (const term of variants) {
        let variantScore = 0;
        if (normalizedName === term || normalizedName.startsWith(term)) {
          variantScore = 5;
        } else if (nameWords.some((word) => word.startsWith(term))) {
          variantScore = 4;
        } else if (normalizedName.includes(term)) {
          variantScore = 3;
        } else if (def.keywords.some((keyword) => keyword.startsWith(term))) {
          variantScore = 2;
        } else if (def.keywords.some((keyword) => keyword.includes(term))) {
          variantScore = 1;
        }
        termScore = Math.max(termScore, variantScore);
      }

      if (termScore === 0) {
        matchesAllTerms = false;
        break;
      }
      total += termScore;
    }

    if (matchesAllTerms) {
      scored.push({ def, score: total });
    }
  }

  scored.sort(
    (a, b) => b.score - a.score || a.def.name.localeCompare(b.def.name),
  );
  return scored.map((entry) => entry.def);
}
