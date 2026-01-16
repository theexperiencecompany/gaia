# Light Mode Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure all hardcoded color classes throughout the application are refactored to use theme-aware semantic tokens, making light mode fully compatible without breaking dark mode.

**Architecture:** The app already has a robust theming system with CSS variables that automatically switch between light/dark modes. The `surface-*` scale handles backgrounds, `foreground-*` handles text, and `border-*` handles borders. All hardcoded `bg-zinc-*`, `bg-gray-*`, `text-gray-*`, `text-white`, `text-black`, `bg-black`, `bg-white` classes need to be replaced with their semantic equivalents.

**Tech Stack:** Next.js 16, Tailwind CSS v4, Custom ThemeProvider, CSS Variables

---

## Color Mapping Reference

### Background Colors
| Hardcoded Class | Light Mode Semantic | Notes |
|-----------------|---------------------|-------|
| `bg-black` | `bg-surface-950` | Darkest background |
| `bg-white` | `bg-surface-50` or `bg-background` | Lightest background |
| `bg-zinc-50` | `bg-surface-50` | |
| `bg-zinc-100` | `bg-surface-100` | |
| `bg-zinc-200` | `bg-surface-200` | |
| `bg-zinc-300` | `bg-surface-300` | |
| `bg-zinc-400` | `bg-surface-400` | |
| `bg-zinc-500` | `bg-surface-500` | |
| `bg-zinc-600` | `bg-surface-600` | |
| `bg-zinc-700` | `bg-surface-700` | |
| `bg-zinc-800` | `bg-surface-800` | |
| `bg-zinc-900` | `bg-surface-900` | |
| `bg-zinc-950` | `bg-surface-950` | |
| `bg-gray-*` | `bg-surface-*` | Same mapping as zinc |
| `bg-neutral-*` | `bg-surface-*` | Same mapping as zinc |
| `bg-slate-*` | `bg-surface-*` | Same mapping as zinc |

### Text Colors
| Hardcoded Class | Semantic Replacement | Notes |
|-----------------|---------------------|-------|
| `text-white` | `text-foreground-900` | Most visible text |
| `text-black` | `text-foreground-900` | Most visible text (inverts in dark) |
| `text-zinc-50` | `text-foreground-50` | Least visible |
| `text-zinc-100` | `text-foreground-100` | |
| `text-zinc-200` | `text-foreground-200` | |
| `text-zinc-300` | `text-foreground-300` | |
| `text-zinc-400` | `text-foreground-400` | Muted text |
| `text-zinc-500` | `text-foreground-500` | Placeholder |
| `text-zinc-600` | `text-foreground-600` | |
| `text-zinc-700` | `text-foreground-700` | |
| `text-zinc-800` | `text-foreground-800` | |
| `text-zinc-900` | `text-foreground-900` | Most visible |
| `text-gray-*` | `text-foreground-*` | Same mapping |

### Special Cases (Keep As-Is or Use dark: Prefix)
- **Status colors**: `bg-red-*`, `bg-green-*`, `bg-blue-*`, `bg-yellow-*` - These are intentionally colored for status indication
- **Gradients for weather**: Keep but ensure they have appropriate opacity
- **Overlays**: `bg-black/50` should use `bg-surface-950/50` or keep for true black overlay
- **Primary buttons with `text-black`**: Use `text-primary-foreground` instead

---

## Phase 1: UI Components (Foundation)

### Task 1.1: Refactor button.tsx
**Files:**
- Modify: `/apps/web/src/components/ui/button.tsx`

**Changes:**
- Replace any `bg-background` with proper semantic if needed
- Ensure all variants work in both themes
- Check `text-*-foreground` patterns are correct

**Verification:** Visual check of all button variants in light/dark mode

---

### Task 1.2: Refactor input.tsx and textarea.tsx
**Files:**
- Modify: `/apps/web/src/components/ui/input.tsx`
- Modify: `/apps/web/src/components/ui/textarea.tsx`

**Changes:**
- `dark:bg-input/30` patterns are fine (already theme-aware)
- Verify placeholder text colors use `text-muted-foreground`

**Verification:** Test input fields in both themes

---

### Task 1.3: Refactor dialog.tsx, drawer.tsx, sheet.tsx
**Files:**
- Modify: `/apps/web/src/components/ui/dialog.tsx`
- Modify: `/apps/web/src/components/ui/drawer.tsx`
- Modify: `/apps/web/src/components/ui/sheet.tsx`

**Changes:**
- `bg-black/50` overlays: Consider keeping for true dark overlay OR use `bg-surface-950/50`
- `bg-background` is correct for content areas

**Verification:** Open modals/sheets in both themes

---

### Task 1.4: Refactor dropdown-menu.tsx and context-menu.tsx
**Files:**
- Modify: `/apps/web/src/components/ui/dropdown-menu.tsx`
- Modify: `/apps/web/src/components/ui/context-menu.tsx`

**Changes:**
- Verify `bg-popover`, `bg-accent` are used correctly
- Check hover states work in light mode

**Verification:** Test dropdown interactions in both themes

---

### Task 1.5: Refactor select.tsx and popover.tsx
**Files:**
- Modify: `/apps/web/src/components/ui/select.tsx`
- Modify: `/apps/web/src/components/ui/popover.tsx`

**Changes:**
- Verify semantic tokens are used
- Check `bg-popover` displays correctly in light mode

**Verification:** Test select dropdowns in both themes

---

### Task 1.6: Refactor calendar.tsx and datetime-picker.tsx
**Files:**
- Modify: `/apps/web/src/components/ui/calendar.tsx`
- Modify: `/apps/web/src/components/ui/datetime-picker.tsx`

**Changes:**
- Replace any hardcoded colors with semantic tokens
- Verify `hover:bg-surface-300` works in light mode

**Verification:** Open date pickers in both themes

---

### Task 1.7: Refactor hero-video-dialog.tsx
**Files:**
- Modify: `/apps/web/src/components/ui/hero-video-dialog.tsx`

**Changes:**
- `bg-black/50` overlay: Keep or change to `bg-surface-950/50`
- `bg-neutral-900/50` -> `bg-surface-900/50`

**Verification:** Test video dialog in both themes

---

### Task 1.8: Refactor holo-card and raised-button
**Files:**
- Modify: `/apps/web/src/components/ui/holo-card/HoloCard.tsx`
- Modify: `/apps/web/src/components/ui/raised-button.tsx`

**Changes:**
- Replace `bg-white/*` and `bg-black/*` with semantic equivalents or add `dark:` variants

**Verification:** Visual check of special effect components

---

### Task 1.9: Refactor multi-step-loader.tsx
**Files:**
- Modify: `/apps/web/src/components/ui/multi-step-loader.tsx`

**Changes:**
- Replace `bg-white` with `bg-background` or `bg-surface-50`
- Check any commented `bg-black` code

**Verification:** Test loader component in both themes

---

### Task 1.10: Refactor ErrorBoundary.tsx
**Files:**
- Modify: `/apps/web/src/components/shared/ErrorBoundary.tsx`

**Changes:**
- Line 29: `bg-black` -> `bg-background` or `bg-surface-950`
- Line 43: `text-gray-400` -> `text-foreground-400`

**Verification:** Trigger error boundary in both themes

---

## Phase 2: Layout Components

### Task 2.1: Refactor sidebar components
**Files:**
- Modify: `/apps/web/src/components/ui/sidebar.tsx`
- Modify: `/apps/web/src/components/layout/sidebar/*.tsx`

**Changes:**
- Verify `bg-secondary-bg` tokens work in light mode
- Check all hover states

**Verification:** Test sidebar interactions in both themes

---

### Task 2.2: Refactor navigation components
**Files:**
- Modify: `/apps/web/src/components/navigation/*.tsx`

**Changes:**
- Replace any hardcoded gradients with theme-aware versions
- Verify transparency overlays work

**Verification:** Test navigation in both themes

---

## Phase 3: Feature Components - Chat

### Task 3.1: Refactor toolIcons.tsx (Critical - Many Hardcoded Colors)
**Files:**
- Modify: `/apps/web/src/features/chat/utils/toolIcons.tsx`

**Changes:**
These are intentional brand/status colors, but text colors need fixing:
- `text-gray-400` (line 158) -> `text-foreground-400`
- Background colors like `bg-emerald-500/20` can stay (status indicators)

**Verification:** Check tool icons display correctly in both themes

---

### Task 3.2: Refactor SlashCommandDropdown.tsx
**Files:**
- Modify: `/apps/web/src/features/chat/components/composer/SlashCommandDropdown.tsx`

**Changes:**
- `text-gray-400` -> `text-foreground-400`

**Verification:** Test slash commands in both themes

---

### Task 3.3: Refactor code-block components
**Files:**
- Modify: `/apps/web/src/features/chat/components/code-block/DownloadButton.tsx`
- Modify: `/apps/web/src/features/chat/components/code-block/MermaidCode.tsx`
- Modify: `/apps/web/src/features/chat/components/code-block/StandardCodeBlock.tsx`
- Modify: `/apps/web/src/features/chat/components/code-block/CustomAnchor.tsx`
- Modify: `/apps/web/src/features/chat/components/code-block/CodeBlock.tsx`
- Modify: `/apps/web/src/features/chat/components/code-block/CopyButton.tsx`
- Modify: `/apps/web/src/features/chat/components/code-block/MermaidTabs.tsx`

**Changes:**
- Replace all `text-gray-*` with `text-foreground-*`

**Verification:** Test code blocks render correctly in both themes

---

### Task 3.4: Refactor chat bubble components
**Files:**
- Modify: `/apps/web/src/features/chat/components/bubbles/bot/TodoSection.tsx`
- Modify: `/apps/web/src/features/chat/components/bubbles/bot/EmailThreadCard.tsx`
- Modify: `/apps/web/src/features/chat/components/bubbles/bot/CodeExecutionSection.tsx`
- Modify: `/apps/web/src/features/chat/components/bubbles/bot/CodeExecutionOutput.tsx`
- Modify: `/apps/web/src/features/chat/components/bubbles/bot/ChartDisplay.tsx`
- Modify: `/apps/web/src/features/chat/components/bubbles/bot/GoogleDocsSection.tsx`

**Changes:**
- Replace `text-gray-*` with `text-foreground-*`
- Replace `text-black` with `text-foreground-900`

**Verification:** Test chat message rendering in both themes

---

### Task 3.5: Refactor memory and file components
**Files:**
- Modify: `/apps/web/src/features/chat/components/memory/MemoryIndicator.tsx`
- Modify: `/apps/web/src/features/chat/components/files/FilePreview.tsx`
- Modify: `/apps/web/src/features/chat/components/files/FileDropModal.tsx`

**Changes:**
- Replace `text-gray-*` with `text-foreground-*`

**Verification:** Test file uploads and memory indicator in both themes

---

## Phase 4: Feature Components - Mail

### Task 4.1: Refactor mail components
**Files:**
- Modify: `/apps/web/src/features/mail/components/ViewMail.tsx`
- Modify: `/apps/web/src/features/mail/components/ContactListCard.tsx`
- Modify: `/apps/web/src/features/mail/components/PeopleSearchCard.tsx`
- Modify: `/apps/web/src/features/mail/components/MailsPage.tsx`
- Modify: `/apps/web/src/features/mail/components/EmailComposeCard.tsx`
- Modify: `/apps/web/src/features/mail/components/EmailListCard.tsx`
- Modify: `/apps/web/src/features/mail/components/AiSearchModal.tsx`
- Modify: `/apps/web/src/features/mail/components/EmailPreviewModal.tsx`
- Modify: `/apps/web/src/features/mail/components/EmailSentCard.tsx`

**Changes:**
- Replace all `text-gray-*` with `text-foreground-*`
- Replace `bg-black/40`, `bg-white/20`, `bg-white` with semantic tokens
- Replace `bg-red-900/20` with theme-aware variant if needed

**Verification:** Test all mail views in both themes

---

## Phase 5: Feature Components - Reddit

### Task 5.1: Refactor reddit components
**Files:**
- Modify: `/apps/web/src/features/reddit/components/RedditSearchCard.tsx`
- Modify: `/apps/web/src/features/reddit/components/RedditCreatedCard.tsx`
- Modify: `/apps/web/src/features/reddit/components/RedditCommentCard.tsx`
- Modify: `/apps/web/src/features/reddit/components/RedditPostCard.tsx`

**Changes:**
- Replace all `text-gray-*` with `text-foreground-*`

**Verification:** Test reddit cards in both themes

---

## Phase 6: Feature Components - Support

### Task 6.1: Refactor support components
**Files:**
- Modify: `/apps/web/src/features/support/components/SupportTicketCard.tsx`
- Modify: `/apps/web/src/features/support/components/ContactSupportModal.tsx`

**Changes:**
- Replace `text-gray-*` with `text-foreground-*`
- Replace `bg-blue-50`, `bg-blue-100` with theme-aware variants: `bg-primary/5`, `bg-primary/10`

**Verification:** Test support UI in both themes

---

## Phase 7: Feature Components - Pricing

### Task 7.1: Refactor pricing components
**Files:**
- Modify: `/apps/web/src/features/pricing/components/ComparisonTable.tsx`
- Modify: `/apps/web/src/features/pricing/components/PaymentStatusIndicator.tsx`
- Modify: `/apps/web/src/features/pricing/components/PricingCards.tsx`
- Modify: `/apps/web/src/features/pricing/components/PricingCard.tsx`
- Modify: `/apps/web/src/features/pricing/components/PaymentSummary.tsx`

**Changes:**
- Replace `text-gray-*` with `text-foreground-*`
- Replace `text-black!` with `text-foreground-900!` or `text-primary-foreground!` for buttons
- Keep status colors (red/green/blue) for indicators

**Verification:** Test pricing page in both themes

---

## Phase 8: Feature Components - Calendar

### Task 8.1: Refactor calendar components
**Files:**
- Modify: `/apps/web/src/features/calendar/components/CalendarListFetchCard.tsx`
- Modify: `/apps/web/src/features/calendar/utils/calendarUtils.ts`

**Changes:**
- Replace `text-gray-*` with `text-foreground-*`
- Calendar event colors (pink, purple, blue, teal) are intentional - keep

**Verification:** Test calendar in both themes

---

## Phase 9: Feature Components - Memory

### Task 9.1: Refactor memory components
**Files:**
- Modify: `/apps/web/src/features/memory/components/MemoryManagement.tsx`

**Changes:**
- Replace `text-gray-400`, `text-gray-500` with `text-foreground-400`, `text-foreground-500`

**Verification:** Test memory management in both themes

---

## Phase 10: Feature Components - Weather

### Task 10.1: Review weather gradients (Special Case)
**Files:**
- Review: `/apps/web/src/features/weather/components/WeatherCard.tsx`
- Review: `/apps/web/src/features/weather/components/WeatherDetailItem.tsx`

**Changes:**
Weather gradients are intentionally colored to represent weather conditions:
- Keep gradient colors (slate, blue, amber, etc.) as they represent weather
- Ensure overlay text is readable: `text-white` may need `dark:text-white text-foreground-900` or similar
- `bg-white/10`, `bg-white/20` -> `bg-surface-50/10`, `bg-surface-50/20`

**Verification:** Test weather cards for all conditions in both themes

---

## Phase 11: Feature Components - Todo

### Task 11.1: Refactor todo components
**Files:**
- Modify: `/apps/web/src/features/todo/components/shared/TodoFieldsRow.tsx`
- Modify: `/apps/web/src/features/todo/components/shared/SubtaskManager.tsx`
- Modify: `/apps/web/src/features/todo/components/fields/DateFieldChip.tsx`
- Modify: `/apps/web/src/features/todo/components/fields/LabelsFieldChip.tsx`
- Modify: `/apps/web/src/features/todo/components/fields/BaseFieldChip.tsx`
- Modify: `/apps/web/src/features/todo/components/fields/ProjectFieldChip.tsx`
- Modify: `/apps/web/src/features/todo/components/fields/PriorityFieldChip.tsx`
- Modify: `/apps/web/src/features/todo/components/WorkflowSection.tsx`
- Modify: `/apps/web/src/features/todo/components/TodoModal.tsx`
- Modify: `/apps/web/src/features/todo/components/TodoItem.tsx`

**Changes:**
- Priority colors (red, yellow, blue) are intentional status indicators - keep
- Verify `bg-surface-*` classes work correctly in light mode

**Verification:** Test todo list in both themes

---

## Phase 12: Feature Components - Workflows

### Task 12.1: Refactor workflow components
**Files:**
- Modify: `/apps/web/src/features/workflows/components/shared/WorkflowStep.tsx`
- Modify: `/apps/web/src/features/workflows/components/WorkflowListView.tsx`
- Modify: `/apps/web/src/features/workflows/components/WorkflowModal.tsx`
- Modify: `/apps/web/src/features/workflows/components/WorkflowSkeletons.tsx`
- Modify: `/apps/web/src/features/workflows/components/WorkflowPage.tsx`
- Modify: `/apps/web/src/features/workflows/components/shared/UnifiedWorkflowCard.tsx`

**Changes:**
- Verify all `bg-surface-*` classes display correctly in light mode
- Check dark: prefixed classes have light mode equivalents

**Verification:** Test workflow pages in both themes

---

## Phase 13: Feature Components - Settings

### Task 13.1: Refactor settings components
**Files:**
- Modify: `/apps/web/src/features/settings/components/SubscriptionSettings.tsx`
- Modify: `/apps/web/src/features/settings/components/UsageSettings.tsx`
- Modify: `/apps/web/src/features/settings/components/SettingsMenu.tsx`

**Changes:**
- Replace `text-black` with `text-foreground-900` or `text-primary-foreground`
- Replace `text-gray-*` with `text-foreground-*`

**Verification:** Test all settings pages in both themes

---

## Phase 14: Feature Components - Onboarding

### Task 14.1: Refactor onboarding components
**Files:**
- Modify: `/apps/web/src/features/onboarding/components/OnboardingInput.tsx`
- Modify: `/apps/web/src/features/onboarding/components/ContextGatheringLoader.tsx`
- Modify: `/apps/web/src/features/onboarding/components/ContextBuildingCard.tsx`

**Changes:**
- Replace `text-black` with appropriate semantic token
- Check `bg-blue-400/50` and similar accent colors

**Verification:** Test onboarding flow in both themes

---

## Phase 15: Feature Components - Landing

### Task 15.1: Refactor landing page components
**Files:**
- Modify: `/apps/web/src/features/landing/components/shared/GetStartedButton.tsx`
- Modify: `/apps/web/src/features/landing/components/sections/OpenSource.tsx`
- Modify: `/apps/web/src/features/landing/components/sections/Productivity.tsx`
- Modify: `/apps/web/src/features/landing/components/demo/DummySlashCommandDropdown.tsx`

**Changes:**
- Replace `text-black!` with `text-primary-foreground!` for primary buttons
- Replace `bg-black`, `bg-black/20`, `bg-black/40` with semantic tokens
- Replace `bg-white/5`, `bg-white/10` with `bg-surface-50/5`, `bg-surface-50/10`
- Replace `bg-gray-700` with `bg-surface-700`
- Replace `text-gray-400` with `text-foreground-400`

**Verification:** Test landing page in both themes

---

## Phase 16: Feature Components - Use Cases

### Task 16.1: Refactor use-cases components
**Files:**
- Modify: `/apps/web/src/features/use-cases/components/UseCaseSection.tsx`
- Modify: `/apps/web/src/features/use-cases/components/UseCaseDetailLayout.tsx`
- Modify: `/apps/web/src/features/use-cases/components/PublishWorkflowCTA.tsx`
- Modify: `/apps/web/src/features/use-cases/components/ToolsList.tsx`
- Modify: `/apps/web/src/features/use-cases/components/MetaInfoCard.tsx`

**Changes:**
- Replace `bg-white/5!` with `bg-surface-50/5!`
- Replace `text-black!` with `text-foreground-900!`

**Verification:** Test use cases pages in both themes

---

## Phase 17: Feature Components - Thanks

### Task 17.1: Refactor thanks components
**Files:**
- Modify: `/apps/web/src/features/thanks/components/Thanks.tsx`
- Modify: `/apps/web/src/features/thanks/components/ToolCard.tsx`

**Changes:**
- Line 29: `bg-black` -> `bg-background`
- Verify surface colors work correctly

**Verification:** Test thanks page in both themes

---

## Phase 18: Feature Components - Notification

### Task 18.1: Refactor notification components
**Files:**
- Modify: `/apps/web/src/features/notification/components/*.tsx`

**Changes:**
- Verify primary colors and red indicators work in both themes

**Verification:** Test notifications in both themes

---

## Phase 19: Utility Files

### Task 19.1: Refactor notification utilities
**Files:**
- Modify: `/apps/web/src/utils/notifications.tsx`
- Modify: `/apps/web/src/utils/interceptorUtils.ts`

**Changes:**
- Status colors (blue, green, yellow, purple, orange) are intentional - verify they're visible in light mode
- `bg-red-500/30` in interceptorUtils is fine for error indication

**Verification:** Trigger notifications and interceptors in both themes

---

### Task 19.2: Refactor useNotificationActions hook
**Files:**
- Modify: `/apps/web/src/hooks/useNotificationActions.ts`

**Changes:**
- `bg-blue-600`, `bg-red-600` for action buttons - these are intentional brand colors, keep
- `bg-surface-700` is already semantic

**Verification:** Test notification actions in both themes

---

## Phase 20: App Pages

### Task 20.1: Refactor payment success page
**Files:**
- Modify: `/apps/web/src/app/(landing)/payment/success/page.tsx`

**Changes:**
- Replace `text-gray-600` with `text-foreground-600`

**Verification:** Test payment success page in both themes

---

### Task 20.2: Refactor dashboard page
**Files:**
- Modify: `/apps/web/src/app/(main)/dashboard/page.tsx`

**Changes:**
- Status colors (emerald, amber, indigo) are intentional indicators - keep

**Verification:** Test dashboard in both themes

---

### Task 20.3: Refactor desktop-login page
**Files:**
- Modify: `/apps/web/src/app/(landing)/desktop-login/page.tsx`

**Changes:**
- `text-emerald-400` is status indicator - keep

**Verification:** Test desktop login in both themes

---

### Task 20.4: Refactor blog pages
**Files:**
- Modify: `/apps/web/src/app/(landing)/blog/page.tsx`
- Modify: `/apps/web/src/features/blog/components/CreateBlogPage.tsx`

**Changes:**
- Verify danger colors are visible in light mode

**Verification:** Test blog pages in both themes

---

## Phase 21: Mobile App (Separate Concern)

### Task 21.1: Audit mobile app colors
**Files:**
- Review: `/apps/mobile/src/**/*.tsx`

**Changes:**
Mobile uses different patterns:
- Many hardcoded hex values: `bg-[#141414]`, `bg-[#0a1929]`, `bg-[#16c1ff]`
- `text-zinc-400` usage in auth screens
- These need separate refactoring to use the mobile theme system

**Note:** This is a separate, larger task - document findings but may need dedicated plan

**Verification:** Test mobile app in both themes

---

## Phase 22: Final Verification

### Task 22.1: Full visual regression test
**Steps:**
1. Navigate through all major pages in light mode
2. Navigate through all major pages in dark mode
3. Toggle between themes on each page
4. Check for any visual inconsistencies
5. Test all interactive components (dropdowns, modals, forms)

**Pages to test:**
- [ ] Landing page
- [ ] Login/Signup
- [ ] Dashboard
- [ ] Chat interface
- [ ] Settings pages
- [ ] Mail interface
- [ ] Calendar
- [ ] Workflows
- [ ] Todos
- [ ] Pricing
- [ ] Blog

---

## Execution Notes

1. **Test after each phase** - Don't batch all changes, verify as you go
2. **Use browser DevTools** - Toggle `.dark` class on `<html>` to quickly test
3. **Priority**: Phases 1-3 are most critical (UI components + chat)
4. **Status colors are intentional** - Don't change red/green/blue/yellow status indicators
5. **Gradients need special attention** - Weather/landing gradients may need careful review
6. **Mobile is separate** - Focus on web first, mobile has different patterns

---

## Quick Reference Commands

```bash
# Find all hardcoded bg-black/white in web app
grep -rn "bg-black\|bg-white" apps/web/src --include="*.tsx"

# Find all hardcoded text-gray-* in web app  
grep -rn "text-gray-" apps/web/src --include="*.tsx"

# Find all hardcoded text-zinc-* in web app
grep -rn "text-zinc-" apps/web/src --include="*.tsx"

# Find all text-white/black in web app
grep -rn "text-white\|text-black" apps/web/src --include="*.tsx"
```
