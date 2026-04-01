# Frontend Dead Code Elimination

Run: `npx knip --config knip.config.ts`

**Rules applied:**
- Keep all `components/ui/` files (prune unused exports only)
- Keep all calendar-related files
- Keep modelsApi and notification-related files
- Keep non-web files (mobile, cli, scripts)
- Keep ErrorBoundary.tsx (documented architectural pattern in typescript.md rules)
- Verified each item before listing

---

## 1. Delete unused files (62)

### Landing page sections (14 files — zero imports anywhere)
- [ ] `apps/web/src/features/landing/components/sections/ChaoticWorkspaceSection.tsx`
- [ ] `apps/web/src/features/landing/components/sections/CommunitySection.tsx`
- [ ] `apps/web/src/features/landing/components/sections/MobileSection.tsx`
- [ ] `apps/web/src/features/landing/components/sections/Personalised.tsx`
- [ ] `apps/web/src/features/landing/components/sections/TestimonialsSection.tsx`
- [ ] `apps/web/src/features/landing/components/sections/TodosBentoContent.tsx`
- [ ] `apps/web/src/features/landing/components/sections/ToolsShowcaseSection.tsx`
- [ ] `apps/web/src/features/landing/components/shared/ContentSection.tsx`
- [ ] `apps/web/src/features/landing/components/shared/FeatureCard.tsx`
- [ ] `apps/web/src/features/landing/components/shared/ImageSelector.tsx`
- [ ] `apps/web/src/features/landing/components/shared/SectionLayout.tsx`
- [ ] `apps/web/src/features/landing/data/testimonials.ts`
- [ ] `apps/web/src/features/landing/layouts/ContentSection.tsx`
- [ ] `apps/web/src/features/landing/layouts/SectionHeader.tsx`

### Layout headers/sidebars (6 files — zero imports)
- [ ] `apps/web/src/components/layout/headers/DefaultHeader.tsx`
- [ ] `apps/web/src/components/layout/headers/HeaderComponent.tsx`
- [ ] `apps/web/src/components/layout/headers/MailHeader.tsx`
- [ ] `apps/web/src/components/layout/sidebar/CloseOpenSidebar.tsx`
- [ ] `apps/web/src/components/layout/sidebar/right-variants/GoalSidebar.tsx`
- [ ] `apps/web/src/components/layout/sidebar/variants/GoalsSidebar.tsx`

### Goals feature (3 files — entire feature unused)
- [ ] `apps/web/src/features/goals/components/GoalCard.tsx`
- [ ] `apps/web/src/features/goals/components/GoalsPage.tsx`
- [ ] `apps/web/src/features/goals/components/GoalsView.tsx`

### Onboarding (3 files — zero imports)
- [ ] `apps/web/src/features/onboarding/components/ContextBuildingCard.tsx`
- [ ] `apps/web/src/features/onboarding/components/OnboardingBackground.tsx`
- [ ] `apps/web/src/features/onboarding/components/OnboardingStepsCard.tsx`

### Pricing/subscription (3 files — zero imports)
- [ ] `apps/web/src/features/pricing/components/PaymentStatusIndicator.tsx`
- [ ] `apps/web/src/features/pricing/components/PaymentSummary.tsx`
- [ ] `apps/web/src/features/pricing/hooks/usePaymentFlow.ts`

### Chat components (5 files — zero imports)
- [ ] `apps/web/src/features/chat/components/files/PdfComponent.tsx`
- [ ] `apps/web/src/features/chat/components/interface/CardStack.tsx`
- [ ] `apps/web/src/features/chat/components/interface/CardStackContainer.tsx`
- [ ] `apps/web/src/features/chat/components/interface/DateSeparator.tsx`
- [ ] `apps/web/src/features/chat/hooks/useIconColorDetection.ts`

### Audio (2 files — MicrophoneBtn all logic commented out, TextToSpeech disabled)
- [ ] `apps/web/src/features/audio/components/MicrophoneBtn.tsx`
- [ ] `apps/web/src/features/audio/components/TextToSpeech.tsx`

### Workflows (3 files — zero imports)
- [ ] `apps/web/src/features/workflows/components/workflow-modal/WorkflowExecutionPanel.tsx`
- [ ] `apps/web/src/features/workflows/data/workflowData.ts`
- [ ] `apps/web/src/features/workflows/utils/workflowUtils.ts`

### Other verified-dead files (20 files)
- [ ] `apps/web/src/components/shared/LabeledField.tsx` — generic boilerplate, zero usage
- [ ] `apps/web/src/components/shared/AnimatedSection.tsx` — superseded by MotionContainer
- [ ] `apps/web/src/components/mdx-components.tsx` — MDX pipeline doesn't use it
- [ ] `apps/web/src/components/navigation/DesktopMenu.tsx`
- [ ] `apps/web/src/data/notifications.ts`
- [ ] `apps/web/src/features/blog/components/BlogListItem.tsx` — superseded by BlogCard
- [ ] `apps/web/src/features/coming-soon/components/ComingSoonModal.tsx` — unused prototype
- [ ] `apps/web/src/features/integrations/hooks/useImageColor.ts`
- [ ] `apps/web/src/features/settings/components/ui/SettingsField.tsx`
- [ ] `apps/web/src/features/subscription/components/SubscriptionActivationBanner.tsx`
- [ ] `apps/web/src/features/todo/components/shared/ActionItemsIndicator.tsx`
- [ ] `apps/web/src/features/use-cases/types/types.ts`
- [ ] `apps/web/src/hooks/useLatestRelease.ts`
- [ ] `apps/web/src/types/features/goalTypes.ts`
- [ ] `apps/web/src/types/features/noteTypes.ts`
- [ ] `apps/web/src/types/shared/modalTypes.ts`
- [ ] `apps/web/src/utils/date/dateTimeLocalUtils.ts`
- [ ] `apps/web/src/utils/notifications.tsx`
- [ ] `apps/web/src/utils/similarity.ts`

---

## 2. Remove unused dependencies (33)

### apps/mobile/package.json
- [ ] `@dev-plugins/react-query`
- [ ] `lucide-react-native`
- [ ] `react-native-keyboard-aware-scroll-view`

### apps/web/package.json
- [ ] `@composio/core`
- [ ] `@lottiefiles/dotlottie-react`
- [ ] `@radix-ui/react-aspect-ratio`
- [ ] `@radix-ui/react-collapsible`
- [ ] `@radix-ui/react-label`
- [ ] `@radix-ui/react-popover`
- [ ] `@radix-ui/react-select`
- [ ] `@radix-ui/react-toggle`
- [ ] `@radix-ui/react-toggle-group`
- [ ] `@react-types/shared`
- [ ] `@types/react-twemoji`
- [ ] `chrono-node`
- [ ] `coolshapes-react`
- [ ] `glob`
- [ ] `html-to-image`
- [ ] `input-otp`
- [ ] `little-date`
- [ ] `madge`
- [ ] `moment-timezone`
- [ ] `next-themes`
- [ ] `npm`
- [ ] `react-day-picker`
- [ ] `react-pdf`
- [ ] `react-swipeable-list`
- [ ] `react-twemoji`
- [ ] `string-similarity`
- [ ] `ts-key-enum`

### packages/cli/package.json
- [ ] `ink-image`
- [ ] `ink-progress-bar`
- [ ] `remove`

---

## 3. Remove unused devDependencies (10)

- [ ] `apps/desktop/package.json`: `@types/wait-on`
- [ ] `apps/mobile/package.json`: `@tailwindcss/postcss`, `eslint`, `eslint-config-expo`, `postcss`, `prettier-plugin-tailwindcss`
- [ ] `apps/web/package.json`: `@types/string-similarity`, `@types/uuid`
- [ ] `packages/cli/package.json`: `@types/react-dom`

---

## 4. Prune unused exports from shadcn UI files (don't delete the files)

### context-menu.tsx (11 exports)
- [ ] `ContextMenuCheckboxItem`, `ContextMenuGroup`, `ContextMenuLabel`, `ContextMenuPortal`, `ContextMenuRadioGroup`, `ContextMenuRadioItem`, `ContextMenuSeparator`, `ContextMenuShortcut`, `ContextMenuSub`, `ContextMenuSubContent`, `ContextMenuSubTrigger`

### dialog.tsx (5 exports)
- [ ] `DialogClose`, `DialogFooter`, `DialogOverlay`, `DialogPortal`, `DialogTrigger`

### dropdown-menu.tsx (9 exports)
- [ ] `DropdownMenuCheckboxItem`, `DropdownMenuGroup`, `DropdownMenuPortal`, `DropdownMenuRadioGroup`, `DropdownMenuRadioItem`, `DropdownMenuShortcut`, `DropdownMenuSub`, `DropdownMenuSubContent`, `DropdownMenuSubTrigger`

### sidebar.tsx (15 exports)
- [ ] `SidebarGroupAction`, `SidebarGroupLabel`, `SidebarInput`, `SidebarMenu`, `SidebarMenuAction`, `SidebarMenuBadge`, `SidebarMenuButton`, `SidebarMenuItem`, `SidebarMenuSkeleton`, `SidebarMenuSub`, `SidebarMenuSubButton`, `SidebarMenuSubItem`, `SidebarRail`, `SidebarSeparator`, `SidebarTrigger`

### Other UI files
- [ ] `button.tsx`: `buttonVariants`
- [ ] `chart.tsx`: `ChartStyle`
- [ ] `scroll-area.tsx`: `ScrollBar`
- [ ] `sheet.tsx`: `SheetClose`, `SheetFooter`

---

## 5. Remove other verified-unused exports

### Store hooks (all confirmed zero imports outside definition file)
- [ ] `composerStore.ts`: `useComposerActions`
- [ ] `holoCardModalStore.ts`: `useHoloCardModalOpen`
- [ ] `integrationModalStore.ts`: `useIntegrationModalOpen`, `useIntegrationModalActions`
- [ ] `integrationsStore.ts`: `useIntegrationsSearchQuery`, `useIntegrationsCategory`
- [ ] `loadingStore.ts`: `useLoadingText`, `useToolInfo`
- [ ] `loginModalStore.ts`: `useLoginModalOpen`
- [ ] `uiStore.ts`: `useUIStore`, `useMenuAccordion`
- [ ] `userStore.ts`: `useUserProfile`, `useUserOnboarding`, `useUserTimezone`
- [ ] `workflowSelectionStore.ts`: `useSelectedWorkflow`, `useWorkflowAutoSend`
- [ ] `todoStore.ts`: `useTodos`, `useTodoProjects`, `useTodoLabels`, `useTodoCounts`, `useTodoLoading`, `useTodoError`

### Feature exports (confirmed unused)
- [ ] `icons.tsx`: `GoogleColouredIcon`, `RetryIcon`
- [ ] `RateLimitToast.tsx`: `showRateLimitExceededToast`
- [ ] `appConfig.tsx`: `personas`
- [ ] `iconPaths.generated.ts`: `iconPaths`
- [ ] `keyboardShortcuts.tsx`: `parseDisplayKeys`, `KEYBOARD_SHORTCUTS`
- [ ] `toolIconConfig.ts`: `webIconUrls`
- [ ] `useFetchUser.ts`: `authPages`, `publicPages`
- [ ] `FilePreview.tsx`: `getFileExtension`
- [ ] `chatUtils.ts`: `fetchMessages`
- [ ] `IntegrationsCard.tsx`: `IntegrationItem`
- [ ] `PublicIntegrationCard.tsx`: `PublicIntegrationCardSkeleton`
- [ ] `categories.ts`: `CATEGORY_LABELS`, `CATEGORY_DISPLAY_PRIORITY`
- [ ] `GmailBody.tsx`: `decodeBase64`
- [ ] `useEmailAnalysis.ts`: `useEmailSummaries`, `useBulkEmailSummaries`, `useEmailAnalysisStatus`, `usePrefetchEmailAnalysis`, `useInvalidateEmailAnalysis`
- [ ] `constants.ts` (notification): `NOTIFICATION_PLATFORMS_SET`
- [ ] `OnboardingIntegrationButtons.tsx`: `OnboardingIntegrationButtons`
- [ ] `houses.ts`: `HOUSES`
- [ ] `usePersonalizationData.ts`: `usePersonalizationData`
- [ ] `commandMenuConfig.tsx`: `PAGE_ITEMS`, `ACTION_ITEMS`, `USER_ITEMS`
- [ ] `settingsConfig.tsx`: `resourceItems`
- [ ] `supportConstants.ts`: `API_ENDPOINTS`
- [ ] `TodoItem.tsx`: `priorityColors`
- [ ] `UnifiedWorkflowCard.tsx`: `WorkflowActionButton`
- [ ] `WorkflowCardComponents.tsx`: `TriggerIcon`, `RunCountDisplay`
- [ ] `WorkflowSkeletons.tsx`: `WorkflowCardSkeleton`, `WorkflowStepSkeleton`, `WorkflowDetailSkeleton`
- [ ] `googleSheets.tsx`: `GoogleSheetsSettings`
- [ ] `registry.ts` (triggers): `getAllHandlers`, `getAllTriggerSlugs`
- [ ] `types/index.ts` (triggers): `isKnownTriggerType`, `isScheduleTrigger`, `isManualTrigger`
- [ ] `utils.ts` (triggers): `normalizeTriggerSlug`, `getTriggerEnabledIntegrations`
- [ ] `cronUtils.ts`: `schedulePresets`

### Utility exports (confirmed unused)
- [ ] `useElectron.ts`: `useIsElectron`
- [ ] `QueryProvider.tsx`: `createIDBPersister`
- [ ] `analytics.ts`: `setUserProperties`, `setGroup`, `optOut`, `optIn`, `isCapturingEnabled`, `posthog`
- [ ] `chatDb.ts`: `messageQueue`, `ChatDexie`
- [ ] `seo.ts`: `commonKeywords`, `getCanonicalUrl`
- [ ] `utils.ts`: `truncateTitle`, `debounce`
- [ ] `colorUtils.ts`: `hexToRgb`, `hslToRgb`
- [ ] `dateUtils.ts`: `parsingDate`, `parseDate2`
- [ ] `timezoneUtils.ts` (date): `getUserTimezone`, `formatTimestampWithTimezone`, `convertToUserTimezone`
- [ ] `formatters.ts`: `formatCompactNumber`, `formatDuration`, `formatRelativeDate`, `getTriggerLabel`
- [ ] `greetingUtils.ts`: `getTimeBasedGreeting`, `getPersonalizedTimeBasedGreeting`
- [ ] `jsonFormatters.ts`: `isPlainObject`, `safeJsonParse`, `looksLikeJson`
- [ ] `playfulThinking.ts`: `PLAYFUL_THINKING_MESSAGES`
- [ ] `seoUtils.ts`: `extractDescription`, `generateBlogStructuredData`
- [ ] `timezoneUtils.ts`: `getTimezoneInfo`, `getPopularTimezones`, `getAllTimezones`, `formatTimezoneDisplay`, `getCurrentTimezoneInfo`

### CLI package exports (confirmed unused)
- [ ] `env-writer.ts`: `getApiEnvPath`, `getWebEnvPath`, `DOCKER_PORT_VAR_MAP`, `envFileExists`, `readEnvFile`
- [ ] `prerequisites.ts`: `checkDocker`, `checkPorts`
- [ ] `service-starter.ts`: `WEB_LOG_FILE`, `checkUrl`, `areServicesRunning`
- [ ] `shared-steps.tsx`: `CheckItem`
- [ ] `Shell.tsx`: `INIT_STEPS`
- [ ] `constants.ts`: `BORDER`
- [ ] `init.tsx`: `StartServicesStep`, `ServicesRunningStep`, `ManualCommandsStep`

---

## 6. Remove unused exported types (28)

- [ ] `blogApi.ts`: `BlogPostCreate`, `BlogPostUpdate`
- [ ] `toolsApi.ts`: `ToolsCategoryResponse`
- [ ] `goals/types.ts`: `GoalNode`
- [ ] `integrations/types/index.ts`: `IntegrationCategory`, `IntegrationActionEvent`, `IntegrationListData`
- [ ] `onboarding/types/websocket.ts`: `OnboardingWebSocketMessage`
- [ ] `triggers/components/types.ts`: `GroupedOption`
- [ ] `triggers/hooks/useInfiniteTriggerOptions.ts`: `TriggerOption`
- [ ] `triggers/types/base.ts`: `TriggerUIHandler`
- [ ] `calendarTypes.ts`: `CalendarCardProps`, `CalendarChipProps`, `CalendarSelectorProps`, `CalendarEventDialogProps`, `EventCardProps`, `UnifiedCalendarEventsListProps`
- [ ] `convoTypes.ts`: `ConversationType`
- [ ] `mailTypes.ts`: `SemanticLabelsStats`
- [ ] `notificationTypes.ts`: `NotificationPreferences`, `CreateNotificationRequest`
- [ ] `todoTypes.ts`: `TodoSearchMode`
- [ ] `toolDataTypes.ts`: `ToolProgressData`, `ToolOutputData`
- [ ] `twitterTypes.ts`: `TwitterData`
- [ ] `notifications.ts`: `GroupedNotifications`
- [ ] `contentTypes.ts`: `ToolInfo`, `StepInfo`
- [ ] `git.ts` (CLI): `CloneProgress`

---

## 7. Fix duplicate exports (3)

- [ ] `EMWorkflowsDemo.tsx`: remove either named or default export
- [ ] `PMWorkflowsDemo.tsx`: remove either named or default export
- [ ] `OnboardingIntegrationButtons.tsx`: remove either named or default export

---

## 8. Remove unused enum members (3)

- [ ] `libs/shared/ts/src/types/notification.ts`: `NotificationStatus.SNOOZED`
- [ ] `libs/shared/ts/src/types/notification.ts`: `NotificationActionStyle.PRIMARY`, `.SECONDARY`

---

## Kept (not in this plan)

- All `components/ui/*.tsx` files (shadcn — only prune exports above)
- All calendar feature files + calendar store + calendar utils
- `modelsApi.ts`, `useModels.ts`, `ModelPickerButton.tsx`
- All notification component files
- `ErrorBoundary.tsx` (documented architectural pattern)
- All non-web files (mobile, CLI, scripts)
- `useOnboardingStore` (used by ContextBuildingCard)
- `SITEMAP_IDS` (used by sitemap route)
- All landing demo components (EMSlackDemo, PMSlackDemo, etc. — used by persona pages)

---

## Execution

After each batch: `nx run-many -t type-check lint --projects=web,desktop`
