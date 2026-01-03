import { Image } from "expo-image";
import { Button, Chip, Popover, type PopoverTriggerRef } from "heroui-native";
import { useRef, useState } from "react";
import { Pressable, ScrollView, TextInput, View } from "react-native";
import { HugeiconsIcon, Search01Icon, Wrench01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

interface Integration {
  id: string;
  name: string;
  description: string;
  logo: string;
  connected: boolean;
}

const INTEGRATIONS: Integration[] = [
  {
    id: "gmail",
    name: "Gmail",
    description: "Read, search, and draft emails securely.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/512px-Gmail_icon_%282020%29.svg.png",
    connected: true,
  },
  {
    id: "github",
    name: "GitHub",
    description: "Access repositories, issues, and pull requests.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/GitHub_Invertocat_Logo.svg/512px-GitHub_Invertocat_Logo.svg.png",
    connected: false,
  },
  {
    id: "calendar",
    name: "Google Calendar",
    description: "Manage your schedule and events.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/512px-Google_Calendar_icon_%282020%29.svg.png",
    connected: false,
  },
  {
    id: "docs",
    name: "Google Docs",
    description: "Create and edit documents collaboratively.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Google_Docs_logo_%282020%29.svg/512px-Google_Docs_logo_%282020%29.svg.png",
    connected: false,
  },
  {
    id: "drive",
    name: "Google Drive",
    description: "Access and organize your files.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/1/12/Google_Drive_icon_%282020%29.svg/512px-Google_Drive_icon_%282020%29.svg.png",
    connected: false,
  },
  {
    id: "maps",
    name: "Google Maps",
    description: "Explore places and get directions.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/aa/Google_Maps_icon_%282020%29.svg/512px-Google_Maps_icon_%282020%29.svg.png",
    connected: false,
  },
  {
    id: "meet",
    name: "Google Meet",
    description: "Video meetings and conferencing.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9b/Google_Meet_icon_%282020%29.svg/512px-Google_Meet_icon_%282020%29.svg.png",
    connected: false,
  },
  {
    id: "sheets",
    name: "Google Sheets",
    description: "Create and edit spreadsheets.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Google_Sheets_logo_%282020%29.svg/512px-Google_Sheets_logo_%282014-2020%29.svg.png",
    connected: false,
  },
  {
    id: "slides",
    name: "Google Slides",
    description: "Create and present slideshows.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/Google_Slides_2020_Logo.svg/512px-Google_Slides_2020_Logo.svg.png",
    connected: false,
  },
  {
    id: "tasks",
    name: "Google Tasks",
    description: "Manage your to-do lists and tasks.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5b/Google_Tasks_2021.svg/512px-Google_Tasks_2021.svg.png",
    connected: false,
  },
  {
    id: "airtable",
    name: "Airtable",
    description: "Organize anything with flexible databases.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/Airtable_Logo.svg/512px-Airtable_Logo.svg.png",
    connected: false,
  },
  {
    id: "asana",
    name: "Asana",
    description: "Track projects and team workflows.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/Asana_logo.svg/512px-Asana_logo.svg.png",
    connected: false,
  },
  {
    id: "clickup",
    name: "ClickUp",
    description: "One app to replace them all.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/ClickUp_Logo.svg/512px-ClickUp_Logo.svg.png",
    connected: false,
  },
  {
    id: "linear",
    name: "Linear",
    description: "Issue tracking built for speed.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Linear_logo.svg/512px-Linear_logo.svg.png",
    connected: false,
  },
  {
    id: "notion",
    name: "Notion",
    description: "All-in-one workspace for notes & docs.",
    logo: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/512px-Notion-logo.svg.png",
    connected: false,
  },
];

const FILTER_OPTIONS = ["All", "Gmail", "GitHub", "Google", "Productivity"];

export function ConnectDrawer() {
  const popoverRef = useRef<PopoverTriggerRef>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFilter, setSelectedFilter] = useState("All");
  const [integrations, setIntegrations] = useState(INTEGRATIONS);

  const handleOpen = () => {
    popoverRef.current?.open();
  };

  const filteredIntegrations = integrations.filter((integration) => {
    const matchesSearch = integration.name
      .toLowerCase()
      .includes(searchQuery.toLowerCase());
    const matchesFilter =
      selectedFilter === "All" ||
      (selectedFilter === "Google" && integration.name.startsWith("Google")) ||
      (selectedFilter === "Productivity" &&
        !integration.name.startsWith("Google") &&
        integration.id !== "gmail" &&
        integration.id !== "github") ||
      integration.name.toLowerCase().includes(selectedFilter.toLowerCase());
    return matchesSearch && matchesFilter;
  });

  const handleConnect = (id: string) => {
    setIntegrations((prev) =>
      prev.map((integration) =>
        integration.id === id
          ? { ...integration, connected: !integration.connected }
          : integration,
      ),
    );
  };

  return (
    <Popover>
      <Popover.Trigger ref={popoverRef} asChild={false}>
        <Button
          variant="tertiary"
          isIconOnly
          size="sm"
          className="rounded-full"
          onPress={handleOpen}
        >
          <HugeiconsIcon icon={Wrench01Icon} size={18} color="#8e8e93" />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Overlay />
        <Popover.Content presentation="bottom-sheet" snapPoints={["70%"]}>
          <View className="flex-row items-center justify-between px-4 pb-4">
            <Popover.Title>Connect Tools</Popover.Title>
            <Popover.Close />
          </View>

          <View className="flex-row items-center px-4 py-2">
            <View className="flex-1 flex-row items-center rounded-xl px-3 py-2 bg-muted/10">
              <HugeiconsIcon icon={Search01Icon} size={18} color="#8e8e93" />
              <TextInput
                className="flex-1 ml-2 text-foreground text-sm"
                placeholder="Search tools..."
                placeholderTextColor="#6b6b6b"
                value={searchQuery}
                onChangeText={setSearchQuery}
              />
            </View>
          </View>

          <ScrollView
            horizontal
            nestedScrollEnabled
            showsHorizontalScrollIndicator={false}
            className="px-4 py-2"
            contentContainerStyle={{ gap: 8 }}
            style={{ flexGrow: 0 }}
          >
            {FILTER_OPTIONS.map((filter) => (
              <Chip
                key={filter}
                variant={selectedFilter === filter ? "primary" : "secondary"}
                color={selectedFilter === filter ? "accent" : "default"}
                onPress={() => setSelectedFilter(filter)}
              >
                <Chip.Label>{filter}</Chip.Label>
              </Chip>
            ))}
          </ScrollView>

          <View className="flex-row items-center justify-between px-4 py-2">
            <Text className="text-sm font-medium">Available Integrations</Text>
            <Text className="text-sm text-muted">
              {filteredIntegrations.filter((i) => i.connected).length}/
              {filteredIntegrations.length}
            </Text>
          </View>

          <ScrollView className="flex-1" showsVerticalScrollIndicator>
            {filteredIntegrations.map((integration) => (
              <Pressable
                key={integration.id}
                onPress={() => handleConnect(integration.id)}
                className="flex-row items-center px-4 py-3 active:bg-muted/10"
              >
                <View className="w-9 h-9 rounded-lg items-center justify-center mr-3">
                  <Image
                    source={{ uri: integration.logo }}
                    style={{ width: 28, height: 28 }}
                    contentFit="contain"
                  />
                </View>

                <View className="flex-1 mr-3">
                  <Text className="font-medium text-sm">
                    {integration.name}
                  </Text>
                  <Text className="text-muted text-xs" numberOfLines={1}>
                    {integration.description}
                  </Text>
                </View>

                <Button
                  size="sm"
                  variant="tertiary"
                  onPress={() => handleConnect(integration.id)}
                  className={
                    integration.connected
                      ? "bg-success/15 px-3 min-w-[90px]"
                      : "bg-muted/10 px-3 min-w-[90px]"
                  }
                >
                  <Button.Label
                    className={
                      integration.connected
                        ? "text-success text-xs"
                        : "text-muted text-xs"
                    }
                  >
                    {integration.connected ? "Connected" : "Connect"}
                  </Button.Label>
                </Button>
              </Pressable>
            ))}
          </ScrollView>
        </Popover.Content>
      </Popover.Portal>
    </Popover>
  );
}
