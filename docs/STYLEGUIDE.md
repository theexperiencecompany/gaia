# Gaia Frontend Style Guide

A comprehensive documentation resource establishing visual and interaction standards for the Gaia application ecosystem.

---

## Table of Contents

- [Overview](#overview)
  - [Introduction](#introduction)
  - [Quick Start](#quick-start)
  - [External Resources](#external-resources)
- [Typography](#typography)
  - [Font Families](#font-families)
  - [Heading Hierarchy](#heading-hierarchy)
  - [Usage Examples](#typography-usage-examples)
- [Colors](#colors)
  - [Primary Colors](#primary-colors)
  - [Semantic Colors](#semantic-colors)
  - [Surface Scale](#surface-scale)
  - [Text Scale](#text-scale)
  - [Border Scale](#border-scale)
  - [Sidebar Colors](#sidebar-colors)
- [Accessibility](#accessibility)
  - [Contrast Requirements](#contrast-requirements)
  - [Accessible Color Combinations](#accessible-color-combinations)
  - [Text Scale Usage](#text-scale-usage)
  - [Selection Highlights](#selection-highlights)
- [Icons](#icons)
  - [Icon Library](#icon-library)
  - [IconProps Interface](#iconprops-interface)
  - [Custom Icons](#custom-icons)
  - [Usage Guidelines](#icon-usage-guidelines)
  - [Common Mistakes](#common-mistakes)
  - [Theme-Aware Icons](#theme-aware-icons)
- [Design Principles](#design-principles)
  - [Core Principles](#core-principles)
  - [Theme System](#theme-system)
  - [Spacing Conventions](#spacing-conventions)
  - [Border Radius](#border-radius)
  - [Animations](#animations)
- [Utilities](#utilities)
  - [Font Access](#font-access)
  - [shadcn/ui Configuration](#shadcnui-configuration)
  - [HeroUI Integration](#heroui-integration)
- [Component Patterns](#component-patterns)
  - [Buttons](#buttons)
  - [Form Inputs](#form-inputs)
  - [Dialogs](#dialogs)
  - [Sidebar](#sidebar)

---

## Overview

### Introduction

Welcome to the Gaia Frontend Style Guide — your single source of truth for building consistent, accessible, and beautiful interfaces across the Gaia ecosystem.

This guide documents the visual and interaction standards that define Gaia's identity. Whether you're designing new features, implementing UI components, or onboarding to the team, you'll find everything you need here.

**Who is this for?**

| Audience | What you'll find |
|----------|------------------|
| **Designers** | Color palettes, typography specs, spacing guidelines, and UI patterns |
| **Developers** | CSS variables, Tailwind classes, component APIs, and code examples |
| **New Team Members** | Quick navigation, onboarding guidance, and foundational principles |

**What's covered?**

- **Typography** — Font families, weights, and heading hierarchy
- **Colors** — Brand colors, semantic tokens, and theme-aware scales
- **Icons** — Icon library, usage patterns, and accessibility
- **Components** — Buttons, forms, dialogs, and layout patterns
- **Principles** — Design philosophy, theming, spacing, and animations

This style guide reflects the actual implementation in the codebase. All values are extracted from `apps/web/src/app/styles/tailwind.css`, font configurations, and component definitions.

### Quick Start

Jump to the section you need:

| Section | Description | Go to |
|---------|-------------|-------|
| 🔤 **Typography** | Font families, weights, and text styles | [Typography](#typography) |
| 🎨 **Colors** | Brand colors, surface scales, and semantic tokens | [Colors](#colors) |
| 🖼️ **Icons** | Icon library, props, and usage guidelines | [Icons](#icons) |
| 🧩 **Components** | Buttons, forms, dialogs, and patterns | [Component Patterns](#component-patterns) |
| ♿ **Accessibility** | Contrast ratios and WCAG compliance | [Accessibility](#accessibility) |
| 📐 **Principles** | Spacing, theming, and animations | [Design Principles](#design-principles) |

**Quick Links:**

- [Primary Brand Color](#primary-colors) — `#00bbff`
- [Font Families](#font-families) — Inter, Instrument Serif, Anonymous Pro
- [Button Variants](#buttons) — default, destructive, outline, secondary, ghost, link
- [Theme System](#theme-system) — Light/dark mode support

### External Resources

#### Fonts (Google Fonts)

| Font | Link | Usage |
|------|------|-------|
| Inter | [fonts.google.com/specimen/Inter](https://fonts.google.com/specimen/Inter) | Primary body text, UI elements |
| Instrument Serif | [fonts.google.com/specimen/Instrument+Serif](https://fonts.google.com/specimen/Instrument+Serif) | Display text, headings, accents |
| Anonymous Pro | [fonts.google.com/specimen/Anonymous+Pro](https://fonts.google.com/specimen/Anonymous+Pro) | Code blocks, monospace text |

> **Note:** Fonts are loaded via Next.js font optimization (`next/font/google`), not direct Google Fonts links. See [Font Access](#font-access) for implementation details.

#### UI Libraries

| Library | Version | Documentation |
|---------|---------|---------------|
| **Tailwind CSS** | v4.x | [tailwindcss.com/docs](https://tailwindcss.com/docs) |
| **shadcn/ui** | new-york style | [ui.shadcn.com](https://ui.shadcn.com) |
| **HeroUI** | v2.8.x | [heroui.com](https://www.heroui.com) |
| **Radix UI** | Various | [radix-ui.com](https://www.radix-ui.com) |

#### Key npm Packages

**Core UI:**
```
@heroui/react                    # HeroUI component library
@theexperiencecompany/gaia-icons # Custom icon library
class-variance-authority         # Component variant management
tailwind-merge                   # Tailwind class merging
clsx                             # Conditional class names
```

**Radix Primitives:**
```
@radix-ui/react-dialog
@radix-ui/react-dropdown-menu
@radix-ui/react-popover
@radix-ui/react-tooltip
@radix-ui/react-accordion
@radix-ui/react-select
```

**Animation & Interaction:**
```
framer-motion                    # Animation library
@use-gesture/react               # Gesture handling
```

#### Configuration Files

| File | Purpose |
|------|---------|
| `apps/web/components.json` | shadcn/ui configuration |
| `apps/web/src/app/styles/tailwind.css` | Tailwind theme and CSS variables |
| `apps/web/src/app/fonts/` | Font configuration files |

---

## Typography

### Font Families

#### Inter

The primary font for body text and UI elements throughout Gaia.

| Property | Value |
|----------|-------|
| **CSS Variable** | `--font-inter` |
| **Tailwind Class** | `font-sans` |
| **Font Stack** | `var(--font-inter), system-ui, sans-serif` |
| **Weights** | All weights (auto-loaded by Next.js) |
| **Subsets** | Latin |

**Usage:**
- Body text and paragraphs
- UI elements (buttons, labels, inputs)
- Navigation items
- Form fields
- Default text throughout the application

**Configuration:**
```typescript
// apps/web/src/app/fonts/inter.ts
import { Inter } from "next/font/google";

export const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
  preload: true,
});
```

**Example:**
```tsx
<p className="font-sans">This text uses Inter.</p>
<span className="font-sans font-medium">Medium weight Inter</span>
<strong className="font-sans font-bold">Bold Inter text</strong>
```

#### Instrument Serif

A display serif font used for headings, accent text, and decorative elements.

| Property | Value |
|----------|-------|
| **CSS Variable** | `--font-instrument-serif` |
| **Tailwind Class** | `font-serif` |
| **Font Stack** | `var(--font-instrument-serif), serif` |
| **Weights** | 400 (Regular only) |
| **Styles** | Normal, Italic |
| **Subsets** | Latin |

**Usage:**
- Display headings and hero text
- Accent text and pull quotes
- Decorative typography elements
- Marketing and landing page headlines

**Configuration:**
```typescript
// apps/web/src/app/fonts/instrument-serif.ts
import { Instrument_Serif } from "next/font/google";

export const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400", // Instrument Serif only has one weight
  variable: "--font-instrument-serif",
  display: "swap",
  preload: true,
  style: "normal",
});
```

**Example:**
```tsx
<h1 className="font-serif text-4xl">Elegant Display Heading</h1>
<blockquote className="font-serif italic">A beautiful pull quote</blockquote>
```

> **Note:** Instrument Serif only comes in weight 400. For bold emphasis, consider using Inter or increasing the font size instead.

#### Anonymous Pro

A monospace font for code blocks, technical content, and fixed-width text.

| Property | Value |
|----------|-------|
| **CSS Variable** | `--font-anonymous-pro` |
| **Tailwind Class** | `font-mono` |
| **Font Stack** | `var(--font-anonymous-pro), ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, "DejaVu Sans Mono", monospace` |
| **Weights** | 400 (Regular), 700 (Bold) |
| **Styles** | Normal, Italic |
| **Subsets** | Latin |

**Usage:**
- Code blocks and inline code
- Terminal/console output
- Technical identifiers (API keys, IDs)
- Data tables with fixed-width requirements
- Keyboard shortcuts

**Configuration:**
```typescript
// apps/web/src/app/fonts/anonymous-pro.ts
import { Anonymous_Pro } from "next/font/google";

export const anonymousPro = Anonymous_Pro({
  subsets: ["latin"],
  weight: ["400", "700"],
  style: ["normal", "italic"],
  variable: "--font-anonymous-pro",
  display: "swap",
  preload: true,
});
```

**Example:**
```tsx
<code className="font-mono">const greeting = "Hello, Gaia!";</code>
<pre className="font-mono text-sm">
  npm install @heroui/react
</pre>
<kbd className="font-mono font-bold">⌘ + K</kbd>
```

### Heading Hierarchy

Gaia uses a consistent heading hierarchy defined in the base layer. All headings use `font-bold` by default.

| Level | Tailwind Classes | Size | Usage |
|-------|------------------|------|-------|
| `h1` | `text-3xl font-bold` | 1.875rem (30px) | Page titles, hero headings |
| `h2` | `text-2xl font-bold` | 1.5rem (24px) | Section headings |
| `h3` | `text-xl font-bold` | 1.25rem (20px) | Subsection headings |
| `h4` | `text-lg font-bold` | 1.125rem (18px) | Card titles, group headings |
| `h5` | `text-base font-bold` | 1rem (16px) | Minor headings |
| `h6` | `text-sm font-bold` | 0.875rem (14px) | Small labels, captions |

**Base Styles (from tailwind.css):**
```css
@layer base {
  h1, h2, h3, h4, h5, h6 {
    @apply text-2xl font-bold;
  }
  h1 { @apply text-3xl; }
  h2 { @apply text-2xl; }
  h3 { @apply text-xl; }
  h4 { @apply text-lg; }
  h5 { @apply text-base; }
  h6 { @apply text-sm; }
}
```

**Visual Reference:**

```
h1 — Page Title (30px bold)
h2 — Section Heading (24px bold)
h3 — Subsection (20px bold)
h4 — Card Title (18px bold)
h5 — Minor Heading (16px bold)
h6 — Small Label (14px bold)
```

> **Tip:** For display headings on landing pages, combine with `font-serif` for a more elegant look:
> ```tsx
> <h1 className="font-serif text-5xl">Welcome to Gaia</h1>
> ```

### Typography Usage Examples

#### Applying Font Classes

```tsx
// Using Tailwind utility classes
<p className="font-sans">Body text with Inter</p>
<h1 className="font-serif">Display heading with Instrument Serif</h1>
<code className="font-mono">Monospace code with Anonymous Pro</code>
```

#### Font Weights

```tsx
// Inter supports all weights (auto-loaded)
<span className="font-sans font-light">Light (300)</span>
<span className="font-sans font-normal">Regular (400)</span>
<span className="font-sans font-medium">Medium (500)</span>
<span className="font-sans font-semibold">Semibold (600)</span>
<span className="font-sans font-bold">Bold (700)</span>

// Anonymous Pro supports 400 and 700
<code className="font-mono font-normal">Regular code</code>
<code className="font-mono font-bold">Bold code</code>
```

#### Complete Typography Component Example

```tsx
// Example: Article layout with proper typography
export function Article({ title, subtitle, content, code }: ArticleProps) {
  return (
    <article className="space-y-6">
      {/* Display heading with serif font */}
      <header>
        <h1 className="font-serif text-4xl text-foreground-900">
          {title}
        </h1>
        <p className="font-sans text-lg text-foreground-500 mt-2">
          {subtitle}
        </p>
      </header>

      {/* Body content with sans-serif */}
      <div className="font-sans text-base text-foreground-800 leading-relaxed">
        {content}
      </div>

      {/* Code block with monospace */}
      {code && (
        <pre className="font-mono text-sm bg-surface-100 dark:bg-surface-200 p-4 rounded-lg overflow-x-auto">
          <code>{code}</code>
        </pre>
      )}
    </article>
  );
}
```

#### Inline Code Styling

```tsx
// Inline code within text
<p className="font-sans">
  Run <code className="font-mono bg-surface-100 dark:bg-surface-200 px-1.5 py-0.5 rounded text-sm">npm install</code> to get started.
</p>
```

#### Combining Fonts

```tsx
// Hero section with mixed typography
<section className="text-center space-y-4">
  <h1 className="font-serif text-5xl md:text-6xl text-foreground-900">
    Welcome to Gaia
  </h1>
  <p className="font-sans text-xl text-foreground-500 max-w-2xl mx-auto">
    Your intelligent assistant for productivity and creativity.
  </p>
  <p className="font-mono text-sm text-foreground-400">
    v2.0.0 • MIT License
  </p>
</section>
```

#### Font Variables in CSS

```css
/* Using CSS variables directly */
.custom-text {
  font-family: var(--font-inter), system-ui, sans-serif;
}

.custom-heading {
  font-family: var(--font-instrument-serif), serif;
}

.custom-code {
  font-family: var(--font-anonymous-pro), ui-monospace, monospace;
}
```

#### Loading Fonts in Layout

```tsx
// apps/web/src/app/layout.tsx
import { getAllFontVariables } from "./fonts";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={getAllFontVariables()}>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
```

---

## Colors

### Primary Colors

The primary brand color is the cornerstone of Gaia's visual identity. It's used for interactive elements, focus states, and brand accents.

#### Brand Primary

| Property | Value |
|----------|-------|
| **Hex** | `#00bbff` |
| **HSL** | `196 100% 50%` |
| **CSS Variable** | `--primary` |
| **Tailwind Class** | `bg-primary`, `text-primary`, `border-primary` |

**Primary Foreground (text on primary):**

| Property | Value |
|----------|-------|
| **Hex** | `#000000` |
| **HSL** | `0 0% 0%` |
| **CSS Variable** | `--primary-foreground` |
| **Tailwind Class** | `text-primary-foreground` |

> **Note:** The primary color remains consistent across light and dark modes. Only the foreground (text on primary) is black to ensure maximum contrast.

**Usage:**

- Primary action buttons
- Links and interactive elements
- Focus rings (`--ring: 196 100% 50%`)
- Selection highlights
- Brand accents and emphasis

**Code Examples:**

```tsx
// Primary button
<button className="bg-primary text-primary-foreground hover:bg-primary/90">
  Get Started
</button>

// Primary text link
<a className="text-primary hover:text-primary/80">Learn more</a>

// Focus ring
<input className="focus:ring-2 focus:ring-primary focus:ring-offset-2" />

// Primary border accent
<div className="border-l-4 border-primary pl-4">
  Highlighted content
</div>
```

**CSS Variables:**

```css
:root {
  --primary: 196 100% 50%;           /* #00bbff */
  --primary-foreground: 0 0% 0%;     /* Black */
  --ring: 196 100% 50%;              /* Focus ring color */
}

.dark {
  --primary: 196 100% 50%;           /* Same in dark mode */
  --primary-foreground: 0 0% 0%;     /* Same in dark mode */
  --ring: 196 100% 50%;
}
```

**HeroUI Integration:**

The primary color is also mapped to HeroUI's theme system:

```css
:root {
  --heroui-primary: #00bbff;
  --heroui-primary-foreground: #000000;
}
```

#### White Color Token

A utility color token for white backgrounds and text:

| Property | Light Mode | Dark Mode |
|----------|------------|-----------|
| **Hex** | `#ffffff` | `#ffffff` |
| **CSS Variable** | `--color-white` | `--color-white` |
| **Foreground** | `#000000` | `#000000` |

```tsx
// White button variant
<button className="bg-white text-white-foreground">
  Secondary Action
</button>
```

### Semantic Colors

Semantic colors convey meaning and state throughout the interface. Each semantic color has both a background value and a foreground (text) value for proper contrast.

#### Secondary

Used for secondary actions and less prominent UI elements.

| Property | Light Mode | Dark Mode |
|----------|------------|-----------|
| **HSL** | `210 40% 96.1%` | `222.2 47.4% 11.2%` |
| **CSS Variable** | `--secondary` | `--secondary` |
| **Tailwind Class** | `bg-secondary` | `bg-secondary` |

| Foreground | Light Mode | Dark Mode |
|------------|------------|-----------|
| **HSL** | `222.2 47.4% 11.2%` | `210 40% 98%` |
| **CSS Variable** | `--secondary-foreground` | `--secondary-foreground` |
| **Tailwind Class** | `text-secondary-foreground` | `text-secondary-foreground` |

```tsx
// Secondary button
<button className="bg-secondary text-secondary-foreground hover:bg-secondary/80">
  Cancel
</button>
```

#### Destructive

Used for dangerous or irreversible actions like delete, remove, or error states.

| Property | Light Mode | Dark Mode |
|----------|------------|-----------|
| **HSL** | `0 84.2% 60.2%` | `0 63% 31%` |
| **CSS Variable** | `--destructive` | `--destructive` |
| **Tailwind Class** | `bg-destructive` | `bg-destructive` |

| Foreground | Light Mode | Dark Mode |
|------------|------------|-----------|
| **HSL** | `0 0% 98%` | `210 40% 98%` |
| **CSS Variable** | `--destructive-foreground` | `--destructive-foreground` |
| **Tailwind Class** | `text-destructive-foreground` | `text-destructive-foreground` |

> **Note:** The destructive color is intentionally more muted in dark mode to reduce visual harshness while maintaining clarity.

```tsx
// Destructive button
<button className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
  Delete Account
</button>

// Destructive text
<span className="text-destructive">This action cannot be undone.</span>
```

#### Muted

Used for subdued backgrounds and de-emphasized text.

| Property | Light Mode | Dark Mode |
|----------|------------|-----------|
| **HSL** | `210 40% 96.1%` | `223 47% 11%` |
| **CSS Variable** | `--muted` | `--muted` |
| **Tailwind Class** | `bg-muted` | `bg-muted` |

| Foreground | Light Mode | Dark Mode |
|------------|------------|-----------|
| **HSL** | `215.4 16.3% 46.9%` | `215.4 16.3% 56.9%` |
| **CSS Variable** | `--muted-foreground` | `--muted-foreground` |
| **Tailwind Class** | `text-muted-foreground` | `text-muted-foreground` |

```tsx
// Muted background section
<div className="bg-muted p-4 rounded-lg">
  <p className="text-muted-foreground">
    Additional information that's less prominent.
  </p>
</div>

// Muted helper text
<span className="text-muted-foreground text-sm">Optional field</span>
```

#### Accent

Used for highlighted or emphasized UI elements that aren't primary actions.

| Property | Light Mode | Dark Mode |
|----------|------------|-----------|
| **HSL** | `210 40% 96.1%` | `216 34% 17%` |
| **CSS Variable** | `--accent` | `--accent` |
| **Tailwind Class** | `bg-accent` | `bg-accent` |

| Foreground | Light Mode | Dark Mode |
|------------|------------|-----------|
| **HSL** | `222.2 47.4% 11.2%` | `210 40% 98%` |
| **CSS Variable** | `--accent-foreground` | `--accent-foreground` |
| **Tailwind Class** | `text-accent-foreground` | `text-accent-foreground` |

```tsx
// Accent hover state
<div className="hover:bg-accent hover:text-accent-foreground rounded-md p-2">
  Hoverable item
</div>

// Accent badge
<span className="bg-accent text-accent-foreground px-2 py-1 rounded-full text-sm">
  New
</span>
```

#### Card & Popover

Surface colors for elevated UI elements like cards, dialogs, and popovers.

| Card | Light Mode | Dark Mode |
|------|------------|-----------|
| **HSL** | `0 0% 100%` | `224 71% 4%` |
| **CSS Variable** | `--card` | `--card` |
| **Tailwind Class** | `bg-card` | `bg-card` |

| Card Foreground | Light Mode | Dark Mode |
|-----------------|------------|-----------|
| **HSL** | `222.2 47.4% 11.2%` | `213 31% 91%` |
| **CSS Variable** | `--card-foreground` | `--card-foreground` |
| **Tailwind Class** | `text-card-foreground` | `text-card-foreground` |

| Popover | Light Mode | Dark Mode |
|---------|------------|-----------|
| **HSL** | `0 0% 100%` | `224 71% 4%` |
| **CSS Variable** | `--popover` | `--popover` |
| **Tailwind Class** | `bg-popover` | `bg-popover` |

| Popover Foreground | Light Mode | Dark Mode |
|--------------------|------------|-----------|
| **HSL** | `222.2 47.4% 11.2%` | `215 20.2% 65.1%` |
| **CSS Variable** | `--popover-foreground` | `--popover-foreground` |
| **Tailwind Class** | `text-popover-foreground` | `text-popover-foreground` |

```tsx
// Card component
<div className="bg-card text-card-foreground rounded-lg border p-6 shadow-sm">
  <h3>Card Title</h3>
  <p>Card content goes here.</p>
</div>

// Popover content
<div className="bg-popover text-popover-foreground rounded-md border p-4 shadow-md">
  Popover content
</div>
```

#### Background & Foreground

The base page colors that define the overall canvas.

| Background | Light Mode | Dark Mode |
|------------|------------|-----------|
| **HSL** | `0 0% 100%` (white) | `240 10% 3.9%` (zinc-950) |
| **CSS Variable** | `--background` | `--background` |
| **Tailwind Class** | `bg-background` | `bg-background` |

| Foreground | Light Mode | Dark Mode |
|------------|------------|-----------|
| **HSL** | `240 5.9% 10%` (zinc-950) | `240 4.8% 95.9%` (zinc-50) |
| **CSS Variable** | `--foreground` | `--foreground` |
| **Tailwind Class** | `text-foreground` | `text-foreground` |

```tsx
// Page layout
<body className="bg-background text-foreground">
  {/* Content */}
</body>
```

#### Border & Input

Default border and input field colors.

| Border | Light Mode | Dark Mode |
|--------|------------|-----------|
| **HSL** | `214.3 31.8% 91.4%` | `216 34% 17%` |
| **CSS Variable** | `--border` | `--border` |
| **Tailwind Class** | `border-border` | `border-border` |

| Input | Light Mode | Dark Mode |
|-------|------------|-----------|
| **HSL** | `214.3 31.8% 91.4%` | `216 34% 17%` |
| **CSS Variable** | `--input` | `--input` |
| **Tailwind Class** | `border-input` | `border-input` |

```tsx
// Input with border
<input className="border border-input rounded-md px-3 py-2 focus:ring-2 focus:ring-ring" />

// Divider
<hr className="border-border" />
```

#### Semantic Colors Quick Reference

| Color | Purpose | Light Mode HSL | Dark Mode HSL |
|-------|---------|----------------|---------------|
| `primary` | Brand actions, links | `196 100% 50%` | `196 100% 50%` |
| `secondary` | Secondary actions | `210 40% 96.1%` | `222.2 47.4% 11.2%` |
| `destructive` | Dangerous actions | `0 84.2% 60.2%` | `0 63% 31%` |
| `muted` | Subdued elements | `210 40% 96.1%` | `223 47% 11%` |
| `accent` | Highlights, hover | `210 40% 96.1%` | `216 34% 17%` |
| `card` | Card backgrounds | `0 0% 100%` | `224 71% 4%` |
| `popover` | Popover backgrounds | `0 0% 100%` | `224 71% 4%` |
| `background` | Page background | `0 0% 100%` | `240 10% 3.9%` |
| `border` | Default borders | `214.3 31.8% 91.4%` | `216 34% 17%` |

### Surface Scale

The surface scale provides a graduated series of background colors from lightest to darkest. In light mode, it follows the Tailwind zinc scale directly. In dark mode, the scale is inverted so that lower numbers remain lighter (relative to the mode) and higher numbers remain darker.

**Key Concept:** Surface colors are theme-aware. `surface-50` is always the lightest surface in the current theme, and `surface-950` is always the darkest. This allows you to use consistent class names regardless of theme.

#### Light Mode

In light mode, the surface scale maps directly to Tailwind's zinc color palette.

| Token | HSL Value | Zinc Equivalent | CSS Variable | Tailwind Class |
|-------|-----------|-----------------|--------------|----------------|
| `surface-50` | `240 4.8% 95.9%` | zinc-50 | `--surface-50` | `bg-surface-50` |
| `surface-100` | `240 4.8% 95.9%` | zinc-100 | `--surface-100` | `bg-surface-100` |
| `surface-200` | `240 5.9% 90%` | zinc-200 | `--surface-200` | `bg-surface-200` |
| `surface-300` | `240 4.9% 83.9%` | zinc-300 | `--surface-300` | `bg-surface-300` |
| `surface-400` | `240 5% 64.9%` | zinc-400 | `--surface-400` | `bg-surface-400` |
| `surface-500` | `240 3.8% 46.1%` | zinc-500 | `--surface-500` | `bg-surface-500` |
| `surface-600` | `240 5.2% 33.9%` | zinc-600 | `--surface-600` | `bg-surface-600` |
| `surface-700` | `240 5.3% 26.1%` | zinc-700 | `--surface-700` | `bg-surface-700` |
| `surface-800` | `240 3.7% 15.9%` | zinc-800 | `--surface-800` | `bg-surface-800` |
| `surface-900` | `240 5.9% 10%` | zinc-900 | `--surface-900` | `bg-surface-900` |
| `surface-950` | `240 10% 3.9%` | zinc-950 | `--surface-950` | `bg-surface-950` |

**Usage Guidelines (Light Mode):**

| Surface | Use Case |
|---------|----------|
| `surface-50` - `surface-100` | Subtle backgrounds, hover states, alternating rows |
| `surface-200` - `surface-300` | Card backgrounds, input fields, code blocks |
| `surface-400` - `surface-500` | Disabled states, placeholder backgrounds |
| `surface-600` - `surface-700` | Dark accents, inverted sections |
| `surface-800` - `surface-950` | Dark overlays, footer backgrounds |

**Code Example:**

```tsx
// Light mode surface usage
<div className="bg-surface-50">Lightest background</div>
<div className="bg-surface-100">Subtle background</div>
<div className="bg-surface-200">Card or input background</div>
<pre className="bg-surface-100 p-4 rounded-lg">Code block</pre>
```

#### Dark Mode

In dark mode, the surface scale is inverted. Lower numbers map to darker zinc values, and higher numbers map to lighter zinc values. This maintains the semantic meaning: `surface-50` is still the "lightest" surface relative to the dark theme.

| Token | HSL Value | Zinc Equivalent | CSS Variable | Tailwind Class |
|-------|-----------|-----------------|--------------|----------------|
| `surface-50` | `240 10% 3.9%` | zinc-950 | `--surface-50` | `bg-surface-50` |
| `surface-100` | `240 5.9% 10%` | zinc-900 | `--surface-100` | `bg-surface-100` |
| `surface-200` | `240 3.7% 15.9%` | zinc-800 | `--surface-200` | `bg-surface-200` |
| `surface-300` | `240 5.3% 26.1%` | zinc-700 | `--surface-300` | `bg-surface-300` |
| `surface-400` | `240 5.2% 33.9%` | zinc-600 | `--surface-400` | `bg-surface-400` |
| `surface-500` | `240 3.8% 46.1%` | zinc-500 | `--surface-500` | `bg-surface-500` |
| `surface-600` | `240 5% 64.9%` | zinc-400 | `--surface-600` | `bg-surface-600` |
| `surface-700` | `240 4.9% 83.9%` | zinc-300 | `--surface-700` | `bg-surface-700` |
| `surface-800` | `240 5.9% 90%` | zinc-200 | `--surface-800` | `bg-surface-800` |
| `surface-900` | `240 4.8% 95.9%` | zinc-100 | `--surface-900` | `bg-surface-900` |
| `surface-950` | `240 4.8% 95.9%` | zinc-50 | `--surface-950` | `bg-surface-950` |

**Usage Guidelines (Dark Mode):**

| Surface | Use Case |
|---------|----------|
| `surface-50` - `surface-100` | Base dark backgrounds, page canvas |
| `surface-200` - `surface-300` | Elevated surfaces, cards, modals |
| `surface-400` - `surface-500` | Borders, dividers, disabled states |
| `surface-600` - `surface-700` | Light accents on dark backgrounds |
| `surface-800` - `surface-950` | Inverted sections, light overlays |

#### Side-by-Side Comparison

| Token | Light Mode (Zinc) | Dark Mode (Zinc) | Purpose |
|-------|-------------------|------------------|---------|
| `surface-50` | zinc-50 (lightest) | zinc-950 (darkest) | Base/lightest surface |
| `surface-100` | zinc-100 | zinc-900 | Subtle elevation |
| `surface-200` | zinc-200 | zinc-800 | Cards, inputs |
| `surface-300` | zinc-300 | zinc-700 | Hover states |
| `surface-400` | zinc-400 | zinc-600 | Borders, dividers |
| `surface-500` | zinc-500 | zinc-500 | Neutral midpoint |
| `surface-600` | zinc-600 | zinc-400 | Muted elements |
| `surface-700` | zinc-700 | zinc-300 | Emphasis |
| `surface-800` | zinc-800 | zinc-200 | Strong contrast |
| `surface-900` | zinc-900 | zinc-100 | Near-inverted |
| `surface-950` | zinc-950 (darkest) | zinc-50 (lightest) | Maximum contrast |

> **Note:** The `surface-500` value is identical in both modes (`240 3.8% 46.1%`), serving as the neutral midpoint of the scale.

#### CSS Variables

```css
/* Light mode (default) */
:root {
  --surface-50: 240 4.8% 95.9%;
  --surface-100: 240 4.8% 95.9%;
  --surface-200: 240 5.9% 90%;
  --surface-300: 240 4.9% 83.9%;
  --surface-400: 240 5% 64.9%;
  --surface-500: 240 3.8% 46.1%;
  --surface-600: 240 5.2% 33.9%;
  --surface-700: 240 5.3% 26.1%;
  --surface-800: 240 3.7% 15.9%;
  --surface-900: 240 5.9% 10%;
  --surface-950: 240 10% 3.9%;
}

/* Dark mode */
.dark {
  --surface-50: 240 10% 3.9%;
  --surface-100: 240 5.9% 10%;
  --surface-200: 240 3.7% 15.9%;
  --surface-300: 240 5.3% 26.1%;
  --surface-400: 240 5.2% 33.9%;
  --surface-500: 240 3.8% 46.1%;
  --surface-600: 240 5% 64.9%;
  --surface-700: 240 4.9% 83.9%;
  --surface-800: 240 5.9% 90%;
  --surface-900: 240 4.8% 95.9%;
  --surface-950: 240 4.8% 95.9%;
}
```

#### Practical Examples

```tsx
// Theme-aware card component
<div className="bg-surface-100 dark:bg-surface-200 rounded-lg p-4 border border-surface-300">
  <h3 className="text-foreground-900">Card Title</h3>
  <p className="text-foreground-600">Card content</p>
</div>

// Code block with surface background
<pre className="bg-surface-100 dark:bg-surface-200 p-4 rounded-lg font-mono text-sm">
  <code>const greeting = "Hello, Gaia!";</code>
</pre>

// Nested elevation
<div className="bg-surface-50 p-6">
  <div className="bg-surface-100 p-4 rounded-lg">
    <div className="bg-surface-200 p-3 rounded-md">
      Nested content with increasing elevation
    </div>
  </div>
</div>

// Hover state
<button className="bg-surface-100 hover:bg-surface-200 transition-colors">
  Hoverable Button
</button>
```

#### Using HSL Values Directly

The surface colors use HSL format without the `hsl()` wrapper, allowing for opacity modifiers:

```tsx
// With opacity modifier
<div className="bg-surface-500/50">50% opacity surface</div>
<div className="bg-surface-200/80">80% opacity surface</div>

// In CSS
.custom-overlay {
  background-color: hsl(var(--surface-900) / 0.8);
}
```

### Text Scale

The text scale provides a graduated series of foreground (text) colors from least visible to most visible. The scale is designed so that **higher numbers = more visible text**. In light mode, higher numbers are darker; in dark mode, higher numbers are lighter.

**Key Concept:** The text scale is semantic, not absolute. `text-900` is always the most visible text color in the current theme, regardless of whether that's dark text on light backgrounds or light text on dark backgrounds.

#### Understanding the Scale

| Visibility | Tokens | Use Case |
|------------|--------|----------|
| **Least visible** | `text-50` - `text-200` | Decorative, disabled, or very subtle text |
| **Low visibility** | `text-300` - `text-400` | Muted text, placeholders, hints |
| **Medium visibility** | `text-500` - `text-600` | Secondary text, captions, metadata |
| **High visibility** | `text-700` - `text-800` | Body text, descriptions |
| **Most visible** | `text-900` | Primary text, headings, important content |

#### Light Mode

In light mode, the text scale uses dark colors on light backgrounds. Higher numbers are darker (more visible).

| Token | HSL Value | Zinc Equivalent | CSS Variable | Tailwind Class |
|-------|-----------|-----------------|--------------|----------------|
| `text-50` | `240 4.8% 95.9%` | zinc-50 | `--text-50` | `text-foreground-50` |
| `text-100` | `240 5.9% 90%` | zinc-200 | `--text-100` | `text-foreground-100` |
| `text-200` | `240 4.9% 83.9%` | zinc-300 | `--text-200` | `text-foreground-200` |
| `text-300` | `240 5% 64.9%` | zinc-400 | `--text-300` | `text-foreground-300` |
| `text-400` | `240 3.8% 46.1%` | zinc-500 | `--text-400` | `text-foreground-400` |
| `text-500` | `240 5.2% 33.9%` | zinc-600 | `--text-500` | `text-foreground-500` |
| `text-600` | `240 5.3% 26.1%` | zinc-700 | `--text-600` | `text-foreground-600` |
| `text-700` | `240 3.7% 15.9%` | zinc-800 | `--text-700` | `text-foreground-700` |
| `text-800` | `240 5.9% 10%` | zinc-900 | `--text-800` | `text-foreground-800` |
| `text-900` | `240 10% 3.9%` | zinc-950 | `--text-900` | `text-foreground-900` |

#### Dark Mode

In dark mode, the text scale is inverted. Higher numbers are lighter (more visible on dark backgrounds).

| Token | HSL Value | Zinc Equivalent | CSS Variable | Tailwind Class |
|-------|-----------|-----------------|--------------|----------------|
| `text-50` | `240 10% 3.9%` | zinc-950 | `--text-50` | `text-foreground-50` |
| `text-100` | `240 5.9% 10%` | zinc-900 | `--text-100` | `text-foreground-100` |
| `text-200` | `240 3.7% 15.9%` | zinc-800 | `--text-200` | `text-foreground-200` |
| `text-300` | `240 5.3% 26.1%` | zinc-700 | `--text-300` | `text-foreground-300` |
| `text-400` | `240 5.2% 33.9%` | zinc-600 | `--text-400` | `text-foreground-400` |
| `text-500` | `240 3.8% 46.1%` | zinc-500 | `--text-500` | `text-foreground-500` |
| `text-600` | `240 5% 64.9%` | zinc-400 | `--text-600` | `text-foreground-600` |
| `text-700` | `240 4.9% 83.9%` | zinc-300 | `--text-700` | `text-foreground-700` |
| `text-800` | `240 5.9% 90%` | zinc-200 | `--text-800` | `text-foreground-800` |
| `text-900` | `240 4.8% 95.9%` | zinc-50 | `--text-900` | `text-foreground-900` |

#### Side-by-Side Comparison

| Token | Light Mode (Zinc) | Dark Mode (Zinc) | Semantic Meaning |
|-------|-------------------|------------------|------------------|
| `text-50` | zinc-50 (lightest) | zinc-950 (darkest) | Least visible |
| `text-100` | zinc-200 | zinc-900 | Very subtle |
| `text-200` | zinc-300 | zinc-800 | Subtle |
| `text-300` | zinc-400 | zinc-700 | Muted |
| `text-400` | zinc-500 | zinc-600 | Placeholder |
| `text-500` | zinc-600 | zinc-500 | Secondary |
| `text-600` | zinc-700 | zinc-400 | Tertiary |
| `text-700` | zinc-800 | zinc-300 | Body text |
| `text-800` | zinc-900 | zinc-200 | Emphasized |
| `text-900` | zinc-950 (darkest) | zinc-50 (lightest) | Most visible |

> **Note:** The `text-400` and `text-500` values serve as the neutral midpoint, commonly used for muted text and placeholders.

#### CSS Variables

```css
/* Light mode (default) */
:root {
  --text-50: 240 4.8% 95.9%;   /* zinc-50 - least visible */
  --text-100: 240 5.9% 90%;    /* zinc-200 */
  --text-200: 240 4.9% 83.9%;  /* zinc-300 */
  --text-300: 240 5% 64.9%;    /* zinc-400 */
  --text-400: 240 3.8% 46.1%;  /* zinc-500 - muted text */
  --text-500: 240 5.2% 33.9%;  /* zinc-600 - placeholder */
  --text-600: 240 5.3% 26.1%;  /* zinc-700 */
  --text-700: 240 3.7% 15.9%;  /* zinc-800 */
  --text-800: 240 5.9% 10%;    /* zinc-900 */
  --text-900: 240 10% 3.9%;    /* zinc-950 - most visible */
}

/* Dark mode */
.dark {
  --text-50: 240 10% 3.9%;     /* zinc-950 - least visible */
  --text-100: 240 5.9% 10%;    /* zinc-900 */
  --text-200: 240 3.7% 15.9%;  /* zinc-800 */
  --text-300: 240 5.3% 26.1%;  /* zinc-700 */
  --text-400: 240 5.2% 33.9%;  /* zinc-600 - muted text */
  --text-500: 240 3.8% 46.1%;  /* zinc-500 - placeholder */
  --text-600: 240 5% 64.9%;    /* zinc-400 */
  --text-700: 240 4.9% 83.9%;  /* zinc-300 */
  --text-800: 240 5.9% 90%;    /* zinc-200 */
  --text-900: 240 4.8% 95.9%;  /* zinc-50 - most visible */
}
```

#### Usage Guidelines

| Token | Recommended Use |
|-------|-----------------|
| `text-foreground-900` | Primary headings, important labels, main content |
| `text-foreground-800` | Body text, descriptions, readable content |
| `text-foreground-700` | Secondary body text, less prominent content |
| `text-foreground-600` | Tertiary text, metadata, timestamps |
| `text-foreground-500` | Placeholder text, input hints |
| `text-foreground-400` | Muted text, disabled labels |
| `text-foreground-300` | Very muted text, subtle hints |
| `text-foreground-200` | Decorative text, watermarks |
| `text-foreground-100` | Near-invisible text, subtle backgrounds |
| `text-foreground-50` | Barely visible, decorative only |

#### Practical Examples

```tsx
// Primary heading - most visible
<h1 className="text-foreground-900 text-3xl font-bold">
  Welcome to Gaia
</h1>

// Body text - high visibility
<p className="text-foreground-800 leading-relaxed">
  This is the main content that users need to read.
</p>

// Secondary text - medium visibility
<span className="text-foreground-600 text-sm">
  Last updated: January 15, 2026
</span>

// Muted/placeholder text - low visibility
<input 
  placeholder="Enter your email..."
  className="placeholder:text-foreground-400"
/>

// Disabled text - very low visibility
<span className="text-foreground-300">
  This feature is coming soon
</span>
```

#### Complete Component Example

```tsx
// Card with proper text hierarchy
export function ArticleCard({ title, excerpt, author, date }: ArticleCardProps) {
  return (
    <article className="bg-surface-100 rounded-lg p-6 space-y-3">
      {/* Primary text - most visible */}
      <h2 className="text-foreground-900 text-xl font-bold">
        {title}
      </h2>
      
      {/* Body text - high visibility */}
      <p className="text-foreground-700 line-clamp-3">
        {excerpt}
      </p>
      
      {/* Metadata - medium visibility */}
      <div className="flex items-center gap-2 text-foreground-500 text-sm">
        <span>{author}</span>
        <span>•</span>
        <time>{date}</time>
      </div>
    </article>
  );
}
```

#### Using HSL Values with Opacity

The text colors use HSL format without the `hsl()` wrapper, allowing for opacity modifiers:

```tsx
// With opacity modifier
<span className="text-foreground-900/80">80% opacity text</span>
<span className="text-foreground-500/50">50% opacity muted text</span>

// In CSS
.custom-text {
  color: hsl(var(--text-900) / 0.9);
}
```

### Border Scale

The border scale provides a graduated series of border colors from subtle to prominent. Unlike the surface and text scales, the border scale starts at `300` (not `50`) because very light borders are rarely useful in practice.

**Key Concept:** Like the text scale, the border scale is semantic. Higher numbers = more visible borders. In light mode, higher numbers are darker; in dark mode, higher numbers are lighter.

#### Understanding the Scale

| Visibility | Tokens | Use Case |
|------------|--------|----------|
| **Subtle** | `border-300` - `border-400` | Dividers, card borders, input borders |
| **Medium** | `border-500` - `border-600` | Emphasized borders, active states |
| **Prominent** | `border-700` - `border-900` | Strong separation, focus indicators |

#### Light Mode

In light mode, the border scale uses darker colors for more visible borders.

| Token | HSL Value | Zinc Equivalent | CSS Variable | Tailwind Class |
|-------|-----------|-----------------|--------------|----------------|
| `border-300` | `240 4.9% 83.9%` | zinc-300 | `--border-300` | `border-border-surface-300` |
| `border-400` | `240 5% 64.9%` | zinc-400 | `--border-400` | `border-border-surface-400` |
| `border-500` | `240 3.8% 46.1%` | zinc-500 | `--border-500` | `border-border-surface-500` |
| `border-600` | `240 5.2% 33.9%` | zinc-600 | `--border-600` | `border-border-surface-600` |
| `border-700` | `240 5.3% 26.1%` | zinc-700 | `--border-700` | `border-border-surface-700` |
| `border-800` | `240 3.7% 15.9%` | zinc-800 | `--border-800` | `border-border-surface-800` |
| `border-900` | `240 5.9% 10%` | zinc-900 | `--border-900` | `border-border-surface-900` |

#### Dark Mode

In dark mode, the border scale is inverted. Higher numbers are lighter (more visible on dark backgrounds).

| Token | HSL Value | Zinc Equivalent | CSS Variable | Tailwind Class |
|-------|-----------|-----------------|--------------|----------------|
| `border-300` | `240 5.3% 26.1%` | zinc-700 | `--border-300` | `border-border-surface-300` |
| `border-400` | `240 5.2% 33.9%` | zinc-600 | `--border-400` | `border-border-surface-400` |
| `border-500` | `240 3.8% 46.1%` | zinc-500 | `--border-500` | `border-border-surface-500` |
| `border-600` | `240 5% 64.9%` | zinc-400 | `--border-600` | `border-border-surface-600` |
| `border-700` | `240 4.9% 83.9%` | zinc-300 | `--border-700` | `border-border-surface-700` |
| `border-800` | `240 5.9% 90%` | zinc-200 | `--border-800` | `border-border-surface-800` |
| `border-900` | `240 4.8% 95.9%` | zinc-100 | `--border-900` | `border-border-surface-900` |

#### Side-by-Side Comparison

| Token | Light Mode (Zinc) | Dark Mode (Zinc) | Semantic Meaning |
|-------|-------------------|------------------|------------------|
| `border-300` | zinc-300 | zinc-700 | Subtle, default borders |
| `border-400` | zinc-400 | zinc-600 | Slightly emphasized |
| `border-500` | zinc-500 | zinc-500 | Neutral midpoint |
| `border-600` | zinc-600 | zinc-400 | Emphasized |
| `border-700` | zinc-700 | zinc-300 | Strong |
| `border-800` | zinc-800 | zinc-200 | Very strong |
| `border-900` | zinc-900 | zinc-100 | Maximum contrast |

> **Note:** The `border-500` value is identical in both modes (`240 3.8% 46.1%`), serving as the neutral midpoint.

#### CSS Variables

```css
/* Light mode (default) */
:root {
  --border-300: 240 4.9% 83.9%;  /* zinc-300 - subtle */
  --border-400: 240 5% 64.9%;    /* zinc-400 */
  --border-500: 240 3.8% 46.1%;  /* zinc-500 - neutral */
  --border-600: 240 5.2% 33.9%;  /* zinc-600 */
  --border-700: 240 5.3% 26.1%;  /* zinc-700 */
  --border-800: 240 3.7% 15.9%;  /* zinc-800 */
  --border-900: 240 5.9% 10%;    /* zinc-900 - prominent */
}

/* Dark mode */
.dark {
  --border-300: 240 5.3% 26.1%;  /* zinc-700 - subtle */
  --border-400: 240 5.2% 33.9%;  /* zinc-600 */
  --border-500: 240 3.8% 46.1%;  /* zinc-500 - neutral */
  --border-600: 240 5% 64.9%;    /* zinc-400 */
  --border-700: 240 4.9% 83.9%;  /* zinc-300 */
  --border-800: 240 5.9% 90%;    /* zinc-200 */
  --border-900: 240 4.8% 95.9%;  /* zinc-100 - prominent */
}
```

#### Usage Guidelines

| Token | Recommended Use |
|-------|-----------------|
| `border-border-surface-300` | Default card borders, dividers, input borders |
| `border-border-surface-400` | Slightly emphasized borders, hover states |
| `border-border-surface-500` | Medium emphasis, active input borders |
| `border-border-surface-600` | Emphasized borders, selected states |
| `border-border-surface-700` | Strong borders, section separators |
| `border-border-surface-800` | Very strong borders, high contrast needs |
| `border-border-surface-900` | Maximum contrast borders, focus indicators |

#### Practical Examples

```tsx
// Default card border - subtle
<div className="border border-border-surface-300 rounded-lg p-4">
  Card content
</div>

// Input with default border
<input 
  className="border border-border-surface-300 rounded-md px-3 py-2 
             focus:border-border-surface-500 focus:ring-2 focus:ring-primary"
/>

// Divider - subtle
<hr className="border-border-surface-300" />

// Emphasized section border
<section className="border-l-4 border-border-surface-600 pl-4">
  Important content
</section>

// Strong separator
<div className="border-t-2 border-border-surface-700 my-8" />
```

#### Complete Component Example

```tsx
// Card with border hierarchy
export function SettingsCard({ title, children, isActive }: SettingsCardProps) {
  return (
    <div 
      className={cn(
        "rounded-lg p-6 transition-colors",
        isActive 
          ? "border-2 border-border-surface-600 bg-surface-100" 
          : "border border-border-surface-300 bg-surface-50"
      )}
    >
      <h3 className="text-foreground-900 font-bold mb-4">{title}</h3>
      
      {/* Content with subtle internal dividers */}
      <div className="space-y-4 divide-y divide-border-surface-300">
        {children}
      </div>
    </div>
  );
}
```

#### Using with Opacity

The border colors use HSL format, allowing for opacity modifiers:

```tsx
// With opacity modifier
<div className="border border-border-surface-500/50">
  50% opacity border
</div>

// In CSS
.custom-border {
  border-color: hsl(var(--border-500) / 0.7);
}
```

#### Default Border vs Border Scale

Gaia also provides a semantic `--border` variable for the default border color:

| Variable | Light Mode | Dark Mode | Use Case |
|----------|------------|-----------|----------|
| `--border` | `214.3 31.8% 91.4%` | `216 34% 17%` | Default semantic border |
| `--border-300` | `240 4.9% 83.9%` | `240 5.3% 26.1%` | Subtle scale border |

```tsx
// Using semantic border (recommended for most cases)
<div className="border border-border">Default border</div>

// Using scale border (for specific visibility needs)
<div className="border border-border-surface-300">Scale border</div>
```

> **Tip:** Use the semantic `border-border` class for most UI elements. Use the scale (`border-border-surface-*`) when you need precise control over border visibility.

### Sidebar Colors

The sidebar has its own dedicated color palette to create visual separation from the main content area. These colors are designed to make the sidebar feel like a distinct, elevated surface while maintaining harmony with the overall theme.

#### Overview

| Property | Purpose |
|----------|---------|
| `sidebar-background` | Main sidebar background color |
| `sidebar-foreground` | Default text color in sidebar |
| `sidebar-primary` | Primary action color in sidebar |
| `sidebar-primary-foreground` | Text on primary elements |
| `sidebar-accent` | Hover and active states |
| `sidebar-accent-foreground` | Text on accent backgrounds |
| `sidebar-border` | Border color for sidebar elements |
| `sidebar-ring` | Focus ring color |
| `sidebar-width` | Fixed width of the sidebar |

#### Light Mode

In light mode, the sidebar uses a slightly elevated gray background (`#f6f6f6`) to distinguish it from the white main content area.

| Token | Value | CSS Variable | Tailwind Class |
|-------|-------|--------------|----------------|
| `sidebar-background` | `#f6f6f6` | `--sidebar-background` | `bg-sidebar` |
| `sidebar-foreground` | `240 5.3% 26.1%` (zinc-700) | `--sidebar-foreground` | `text-sidebar-foreground` |
| `sidebar-primary` | `240 5.9% 10%` (zinc-900) | `--sidebar-primary` | `bg-sidebar-primary` |
| `sidebar-primary-foreground` | `0 0% 98%` | `--sidebar-primary-foreground` | `text-sidebar-primary-foreground` |
| `sidebar-accent` | `240 5.9% 90%` (zinc-200) | `--sidebar-accent` | `bg-sidebar-accent` |
| `sidebar-accent-foreground` | `240 5.9% 10%` (zinc-900) | `--sidebar-accent-foreground` | `text-sidebar-accent-foreground` |
| `sidebar-border` | `220 13% 91%` | `--sidebar-border` | `border-sidebar-border` |
| `sidebar-ring` | `217.2 91.2% 59.8%` | `--sidebar-ring` | `ring-sidebar-ring` |
| `sidebar-width` | `250px` | `--sidebar-width` | — |

#### Dark Mode

In dark mode, the sidebar uses a dark gray background (`#1a1a1a`) that's slightly lighter than the main content area to maintain the elevated appearance.

| Token | Value | CSS Variable | Tailwind Class |
|-------|-------|--------------|----------------|
| `sidebar-background` | `#1a1a1a` | `--sidebar-background` | `bg-sidebar` |
| `sidebar-foreground` | `240 4.8% 95.9%` (zinc-50) | `--sidebar-foreground` | `text-sidebar-foreground` |
| `sidebar-primary` | `224.3 76.3% 48%` | `--sidebar-primary` | `bg-sidebar-primary` |
| `sidebar-primary-foreground` | `0 0% 100%` | `--sidebar-primary-foreground` | `text-sidebar-primary-foreground` |
| `sidebar-accent` | `240 3.7% 15.9%` (zinc-800) | `--sidebar-accent` | `bg-sidebar-accent` |
| `sidebar-accent-foreground` | `240 4.8% 95.9%` (zinc-50) | `--sidebar-accent-foreground` | `text-sidebar-accent-foreground` |
| `sidebar-border` | `240 3.7% 15.9%` (zinc-800) | `--sidebar-border` | `border-sidebar-border` |
| `sidebar-ring` | `217.2 91.2% 59.8%` | `--sidebar-ring` | `ring-sidebar-ring` |
| `sidebar-width` | `250px` | `--sidebar-width` | — |

#### Side-by-Side Comparison

| Token | Light Mode | Dark Mode |
|-------|------------|-----------|
| `background` | `#f6f6f6` (light gray) | `#1a1a1a` (dark gray) |
| `foreground` | zinc-700 (dark text) | zinc-50 (light text) |
| `primary` | zinc-900 | Blue (`224.3 76.3% 48%`) |
| `accent` | zinc-200 (subtle hover) | zinc-800 (subtle hover) |
| `border` | Light gray | zinc-800 |

#### CSS Variables

```css
/* Light mode (default) */
:root {
  --sidebar-width: 250px;
  --sidebar-background: #f6f6f6;
  --sidebar-foreground: 240 5.3% 26.1%;        /* zinc-700 */
  --sidebar-primary: 240 5.9% 10%;             /* zinc-900 */
  --sidebar-primary-foreground: 0 0% 98%;
  --sidebar-accent: 240 5.9% 90%;              /* zinc-200 */
  --sidebar-accent-foreground: 240 5.9% 10%;   /* zinc-900 */
  --sidebar-border: 220 13% 91%;
  --sidebar-ring: 217.2 91.2% 59.8%;
}

/* Dark mode */
.dark {
  --sidebar-width: 250px;
  --sidebar-background: #1a1a1a;
  --sidebar-foreground: 240 4.8% 95.9%;        /* zinc-50 */
  --sidebar-primary: 224.3 76.3% 48%;          /* Blue */
  --sidebar-primary-foreground: 0 0% 100%;
  --sidebar-accent: 240 3.7% 15.9%;            /* zinc-800 */
  --sidebar-accent-foreground: 240 4.8% 95.9%; /* zinc-50 */
  --sidebar-border: 240 3.7% 15.9%;            /* zinc-800 */
  --sidebar-ring: 217.2 91.2% 59.8%;
}
```

#### Theme Aliases

The sidebar colors are also available through theme aliases for convenience:

```css
@theme {
  --color-secondary-bg: var(--sidebar-background);
  --color-secondary-bg-accent: hsl(var(--sidebar-accent));
  --color-secondary-bg-border: hsl(var(--sidebar-border));
}
```

#### Usage Guidelines

| Element | Recommended Classes |
|---------|---------------------|
| Sidebar container | `bg-sidebar w-[var(--sidebar-width)]` |
| Sidebar text | `text-sidebar-foreground` |
| Navigation items | `text-sidebar-foreground hover:bg-sidebar-accent` |
| Active nav item | `bg-sidebar-accent text-sidebar-accent-foreground` |
| Primary action | `bg-sidebar-primary text-sidebar-primary-foreground` |
| Sidebar border | `border-sidebar-border` |
| Focus states | `focus:ring-sidebar-ring` |

#### Practical Examples

```tsx
// Basic sidebar structure
<aside 
  className="bg-sidebar w-[var(--sidebar-width)] h-screen border-r border-sidebar-border"
>
  <nav className="p-4">
    <ul className="space-y-1">
      {/* Navigation items */}
    </ul>
  </nav>
</aside>

// Navigation item
<li>
  <a 
    href="/dashboard"
    className="flex items-center gap-3 px-3 py-2 rounded-md
               text-sidebar-foreground 
               hover:bg-sidebar-accent hover:text-sidebar-accent-foreground
               transition-colors"
  >
    <DashboardIcon className="size-5" />
    <span>Dashboard</span>
  </a>
</li>

// Active navigation item
<li>
  <a 
    href="/settings"
    className="flex items-center gap-3 px-3 py-2 rounded-md
               bg-sidebar-accent text-sidebar-accent-foreground"
  >
    <SettingsIcon className="size-5" />
    <span>Settings</span>
  </a>
</li>

// Primary action button in sidebar
<button 
  className="w-full px-3 py-2 rounded-md
             bg-sidebar-primary text-sidebar-primary-foreground
             hover:bg-sidebar-primary/90 transition-colors"
>
  New Project
</button>
```

#### Complete Sidebar Component Example

```tsx
export function Sidebar({ navigation, currentPath }: SidebarProps) {
  return (
    <aside 
      className="fixed left-0 top-0 h-screen w-[var(--sidebar-width)]
                 bg-sidebar border-r border-sidebar-border
                 flex flex-col"
    >
      {/* Logo area */}
      <div className="p-4 border-b border-sidebar-border">
        <Logo className="h-8 text-sidebar-foreground" />
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 overflow-y-auto">
        <ul className="space-y-1">
          {navigation.map((item) => (
            <li key={item.href}>
              <a
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 rounded-md transition-colors",
                  currentPath === item.href
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/50"
                )}
              >
                <item.icon className="size-5" />
                <span>{item.label}</span>
              </a>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer action */}
      <div className="p-4 border-t border-sidebar-border">
        <button 
          className="w-full px-3 py-2 rounded-md
                     bg-sidebar-primary text-sidebar-primary-foreground
                     hover:bg-sidebar-primary/90 transition-colors
                     focus:outline-none focus:ring-2 focus:ring-sidebar-ring"
        >
          Create New
        </button>
      </div>
    </aside>
  );
}
```

#### Sidebar vs Main Content

The sidebar is intentionally styled differently from the main content area:

| Aspect | Main Content | Sidebar |
|--------|--------------|---------|
| Background (Light) | `#ffffff` (white) | `#f6f6f6` (light gray) |
| Background (Dark) | `#141414` | `#1a1a1a` (slightly lighter) |
| Purpose | Primary content area | Navigation and secondary actions |
| Width | Flexible | Fixed `250px` |

This creates a clear visual hierarchy where the sidebar feels like a persistent navigation panel alongside the main content.

---

## Accessibility

Accessibility is a core principle of Gaia's design system. This section documents the standards and guidelines for ensuring all users can effectively interact with the interface, regardless of visual ability.

### Contrast Requirements

Gaia follows the Web Content Accessibility Guidelines (WCAG) 2.1 Level AA standards for color contrast. These requirements ensure text remains readable for users with low vision or color blindness.

#### WCAG AA Minimum Contrast Ratios

| Text Type | Minimum Ratio | Description |
|-----------|---------------|-------------|
| **Normal text** | 4.5:1 | Text smaller than 18pt (24px) or 14pt (18.67px) bold |
| **Large text** | 3:1 | Text 18pt (24px) or larger, or 14pt (18.67px) bold or larger |
| **UI components** | 3:1 | Interactive elements, icons, and graphical objects |
| **Focus indicators** | 3:1 | Focus rings and keyboard navigation indicators |

#### What Counts as Large Text?

| Size | Weight | Classification |
|------|--------|----------------|
| ≥ 24px (1.5rem) | Any weight | Large text |
| ≥ 18.67px (1.167rem) | Bold (700) | Large text |
| < 24px | Normal (400-600) | Normal text |
| < 18.67px | Bold (700) | Normal text |

#### Gaia Heading Contrast

All Gaia headings use `font-bold` (700 weight), which affects their contrast requirements:

| Heading | Size | Weight | Classification | Required Ratio |
|---------|------|--------|----------------|----------------|
| `h1` | 30px (1.875rem) | Bold | Large text | 3:1 |
| `h2` | 24px (1.5rem) | Bold | Large text | 3:1 |
| `h3` | 20px (1.25rem) | Bold | Large text | 3:1 |
| `h4` | 18px (1.125rem) | Bold | Normal text | 4.5:1 |
| `h5` | 16px (1rem) | Bold | Normal text | 4.5:1 |
| `h6` | 14px (0.875rem) | Bold | Normal text | 4.5:1 |

#### Testing Contrast

Use these tools to verify contrast ratios:

- **WebAIM Contrast Checker**: [webaim.org/resources/contrastchecker](https://webaim.org/resources/contrastchecker/)
- **Chrome DevTools**: Inspect element → Color picker shows contrast ratio
- **Figma**: Use the A11y - Color Contrast plugin

#### Code Example: Ensuring Contrast

```tsx
// ✅ Good: High contrast text on surface
<div className="bg-surface-100">
  <p className="text-foreground-900">Primary text (high contrast)</p>
  <p className="text-foreground-700">Body text (good contrast)</p>
</div>

// ⚠️ Caution: Lower contrast - verify meets 4.5:1
<div className="bg-surface-100">
  <p className="text-foreground-500">Secondary text (verify contrast)</p>
</div>

// ❌ Avoid: Low contrast combinations
<div className="bg-surface-200">
  <p className="text-foreground-300">Hard to read text</p>
</div>
```

### Accessible Color Combinations

This section documents which text/background color combinations meet WCAG AA standards. Use these combinations to ensure your interfaces are accessible to all users.

#### WCAG AA Compliant Combinations

##### Light Mode (White/Light Backgrounds)

| Background | Text Color | Contrast Ratio | Status |
|------------|------------|----------------|--------|
| `surface-50` | `text-foreground-900` | ~19:1 | ✅ Excellent |
| `surface-50` | `text-foreground-800` | ~15:1 | ✅ Excellent |
| `surface-50` | `text-foreground-700` | ~10:1 | ✅ Excellent |
| `surface-50` | `text-foreground-600` | ~7:1 | ✅ AA Pass |
| `surface-50` | `text-foreground-500` | ~5:1 | ✅ AA Pass |
| `surface-100` | `text-foreground-900` | ~18:1 | ✅ Excellent |
| `surface-100` | `text-foreground-700` | ~9:1 | ✅ Excellent |
| `surface-200` | `text-foreground-900` | ~16:1 | ✅ Excellent |
| `surface-200` | `text-foreground-700` | ~8:1 | ✅ Excellent |

##### Dark Mode (Dark Backgrounds)

| Background | Text Color | Contrast Ratio | Status |
|------------|------------|----------------|--------|
| `surface-50` (dark) | `text-foreground-900` | ~19:1 | ✅ Excellent |
| `surface-50` (dark) | `text-foreground-800` | ~15:1 | ✅ Excellent |
| `surface-50` (dark) | `text-foreground-700` | ~10:1 | ✅ Excellent |
| `surface-100` (dark) | `text-foreground-900` | ~17:1 | ✅ Excellent |
| `surface-200` (dark) | `text-foreground-900` | ~14:1 | ✅ Excellent |

##### Primary Color Combinations

| Background | Text Color | Contrast Ratio | Status |
|------------|------------|----------------|--------|
| `primary` (#00bbff) | `primary-foreground` (black) | ~8:1 | ✅ Excellent |
| `surface-50` | `text-primary` | ~3.5:1 | ✅ Large text only |
| `surface-950` | `text-primary` | ~8:1 | ✅ Excellent |

##### Semantic Color Combinations

| Background | Text Color | Status | Notes |
|------------|------------|--------|-------|
| `destructive` | `destructive-foreground` | ✅ AA Pass | Red on white |
| `secondary` | `secondary-foreground` | ✅ AA Pass | Both modes |
| `muted` | `muted-foreground` | ✅ AA Pass | Both modes |
| `accent` | `accent-foreground` | ✅ AA Pass | Both modes |
| `card` | `card-foreground` | ✅ AA Pass | Both modes |

#### Non-Compliant Combinations to Avoid

These combinations do NOT meet WCAG AA standards and should be avoided:

| Background | Text Color | Contrast Ratio | Issue |
|------------|------------|----------------|-------|
| `surface-50` | `text-foreground-400` | ~3.5:1 | ❌ Below 4.5:1 |
| `surface-50` | `text-foreground-300` | ~2.5:1 | ❌ Below 4.5:1 |
| `surface-100` | `text-foreground-300` | ~2.3:1 | ❌ Below 4.5:1 |
| `surface-200` | `text-foreground-400` | ~3:1 | ❌ Below 4.5:1 |
| `surface-300` | `text-foreground-500` | ~2:1 | ❌ Below 4.5:1 |

#### Accessible Alternatives

When you need subtle text but must maintain accessibility:

| Instead of... | Use... | Notes |
|---------------|--------|-------|
| `text-foreground-300` | `text-foreground-500` | Minimum for readable muted text |
| `text-foreground-400` | `text-foreground-500` | Safe for placeholder text |
| `text-foreground-200` on `surface-100` | `text-foreground-600` on `surface-100` | For secondary content |

#### Recommended Text Hierarchy

Use this hierarchy to ensure both visual hierarchy and accessibility:

```tsx
// Accessible text hierarchy
<article className="bg-surface-50 p-6 space-y-4">
  {/* Primary content - highest contrast */}
  <h1 className="text-foreground-900 text-3xl font-bold">
    Page Title
  </h1>
  
  {/* Body text - high contrast */}
  <p className="text-foreground-800">
    Main body content that users need to read.
  </p>
  
  {/* Secondary text - good contrast */}
  <p className="text-foreground-600">
    Supporting information and descriptions.
  </p>
  
  {/* Muted text - minimum accessible contrast */}
  <span className="text-foreground-500 text-sm">
    Metadata, timestamps, or hints
  </span>
  
  {/* ⚠️ Below this point, use only for decorative purposes */}
</article>
```

#### Interactive Element Contrast

Interactive elements have additional contrast requirements:

```tsx
// Button with accessible contrast
<button className="bg-primary text-primary-foreground">
  Primary Action {/* Black on cyan - 8:1 ratio */}
</button>

// Link with accessible contrast
<a className="text-primary hover:text-primary/80">
  Learn more {/* Cyan on white - use on dark backgrounds for best contrast */}
</a>

// Input with visible border
<input 
  className="border border-border-surface-400 text-foreground-900
             placeholder:text-foreground-500"
  placeholder="Accessible placeholder"
/>
```

#### Focus State Contrast

Focus indicators must have at least 3:1 contrast against adjacent colors:

```tsx
// Accessible focus ring
<button 
  className="focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
>
  Focusable Button
</button>

// The primary color (#00bbff) provides sufficient contrast for focus rings
```

### Text Scale Usage

The text scale (`text-foreground-50` through `text-foreground-900`) is designed with accessibility in mind. Understanding the semantic meaning of each level helps you create readable, accessible interfaces.

#### Semantic Meaning of Scale Numbers

The text scale follows a simple principle: **higher numbers = more visible text**.

| Scale Range | Visibility | Accessibility | Recommended Use |
|-------------|------------|---------------|-----------------|
| `900` | Maximum | ✅ Always accessible | Primary headings, critical content |
| `800` | Very High | ✅ Always accessible | Body text, important information |
| `700` | High | ✅ Always accessible | Secondary body text, descriptions |
| `600` | Medium-High | ✅ Accessible | Tertiary text, captions |
| `500` | Medium | ✅ Minimum accessible | Placeholder text, hints, metadata |
| `400` | Low | ⚠️ Large text only | Decorative, disabled states |
| `300` | Very Low | ❌ Not accessible | Decorative only, not for content |
| `200` | Minimal | ❌ Not accessible | Watermarks, subtle decoration |
| `100` | Near-invisible | ❌ Not accessible | Background decoration only |
| `50` | Invisible | ❌ Not accessible | Not for text content |

#### Best Practices for Readability

##### 1. Use the Right Scale for Content Importance

```tsx
// ✅ Correct: Scale matches content importance
<article>
  <h1 className="text-foreground-900">Most Important</h1>
  <p className="text-foreground-800">Primary content</p>
  <p className="text-foreground-600">Supporting details</p>
  <span className="text-foreground-500">Metadata</span>
</article>

// ❌ Incorrect: Important content with low visibility
<article>
  <h1 className="text-foreground-500">Hard to read heading</h1>
  <p className="text-foreground-400">Body text too light</p>
</article>
```

##### 2. Never Use Below 500 for Readable Content

```tsx
// ✅ Accessible placeholder
<input placeholder="Enter email" className="placeholder:text-foreground-500" />

// ❌ Inaccessible placeholder
<input placeholder="Enter email" className="placeholder:text-foreground-300" />
```

##### 3. Consider Background Color

The same text scale value may have different contrast depending on the background:

```tsx
// ✅ Good: Lighter background allows slightly lower text values
<div className="bg-surface-50">
  <p className="text-foreground-600">Readable on light background</p>
</div>

// ⚠️ Caution: Darker backgrounds need higher text values
<div className="bg-surface-200">
  <p className="text-foreground-700">Need higher value on darker surface</p>
</div>
```

##### 4. Maintain Visual Hierarchy

Create clear hierarchy using the scale:

```tsx
// Clear visual hierarchy with accessible contrast
<div className="space-y-2">
  {/* Level 1: Primary - Maximum visibility */}
  <h2 className="text-foreground-900 text-xl font-bold">
    Section Title
  </h2>
  
  {/* Level 2: Secondary - High visibility */}
  <p className="text-foreground-800">
    Main description that users need to read and understand.
  </p>
  
  {/* Level 3: Tertiary - Good visibility */}
  <p className="text-foreground-600 text-sm">
    Additional context or supporting information.
  </p>
  
  {/* Level 4: Quaternary - Minimum accessible */}
  <span className="text-foreground-500 text-xs">
    Last updated: January 15, 2026
  </span>
</div>
```

##### 5. Disabled States

For disabled elements, use lower contrast but ensure the disabled state is communicated through other means:

```tsx
// Disabled button with visual indicators beyond just color
<button 
  disabled
  className="text-foreground-400 bg-surface-200 cursor-not-allowed opacity-60"
  aria-disabled="true"
>
  Disabled Action
</button>
```

#### Quick Reference: Safe Text Values

| Use Case | Minimum Safe Value | Recommended Value |
|----------|-------------------|-------------------|
| Headings | `text-foreground-800` | `text-foreground-900` |
| Body text | `text-foreground-700` | `text-foreground-800` |
| Secondary text | `text-foreground-600` | `text-foreground-600` |
| Captions/metadata | `text-foreground-500` | `text-foreground-500` |
| Placeholders | `text-foreground-500` | `text-foreground-500` |
| Disabled text | `text-foreground-400` | Use with other indicators |
| Decorative only | Any | Not for readable content |

#### Testing Text Readability

1. **Squint test**: If you squint and can't read the text, it's too light
2. **Grayscale test**: View in grayscale to check contrast without color
3. **Zoom test**: Text should remain readable at 200% zoom
4. **Tool verification**: Use contrast checkers for exact ratios

### Selection Highlights

Text selection (highlighting) uses the primary brand color to maintain visual consistency while ensuring selected text remains readable.

#### Default Selection Colors

Gaia uses a semi-transparent primary color for selection backgrounds:

| Property | Value | CSS |
|----------|-------|-----|
| **Background** | Primary at 20% opacity | `hsl(var(--primary) / 0.2)` |
| **Text Color** | Primary | `hsl(var(--primary))` |

```css
/* From globals.css */
::selection {
  background: hsl(var(--primary) / 0.2);  /* #00bbff at 20% opacity */
  color: hsl(var(--primary));              /* #00bbff */
}
```

#### Why These Colors?

1. **Brand consistency**: Selection uses the primary brand color (#00bbff)
2. **Readability**: 20% opacity background doesn't obscure text
3. **Visibility**: Primary color text stands out against the subtle background
4. **Theme-aware**: Works in both light and dark modes

#### Chat Bubble Selection

Chat bubbles use a different selection style for better contrast against message backgrounds:

```css
.chat_bubble::selection {
  background: hsl(var(--surface-950));  /* Dark background */
  color: hsl(var(--primary));           /* Primary text */
}
```

This provides higher contrast for text selection within chat messages.

#### Accessibility Considerations

| Aspect | Implementation | Status |
|--------|----------------|--------|
| **Background contrast** | 20% opacity maintains text readability | ✅ |
| **Text visibility** | Primary color provides clear indication | ✅ |
| **Theme support** | Works in light and dark modes | ✅ |
| **Keyboard users** | Selection visible during keyboard navigation | ✅ |

#### Custom Selection Styles

If you need custom selection colors for specific components:

```css
/* High contrast selection for dark backgrounds */
.dark-section ::selection {
  background: hsl(var(--primary) / 0.3);
  color: hsl(var(--primary));
}

/* Inverted selection for special areas */
.inverted-section ::selection {
  background: hsl(var(--surface-900));
  color: hsl(var(--surface-50));
}
```

#### Testing Selection Accessibility

1. **Select text** in various areas of the interface
2. **Verify readability** of selected text against the highlight background
3. **Test in both themes** (light and dark mode)
4. **Check keyboard selection** using Shift + Arrow keys

---

## Icons

Gaia uses a custom icon library combined with locally-defined custom icons. All icons are SVG-based and support consistent sizing, coloring, and accessibility features.

### Icon Library

The primary icon library is `@theexperiencecompany/gaia-icons`, specifically the `solid-rounded` variant. Icons are re-exported through a central file for consistent usage across the application.

#### Source

| Property | Value |
|----------|-------|
| **Package** | `@theexperiencecompany/gaia-icons` |
| **Variant** | `solid-rounded` |
| **Export File** | `apps/web/src/components/shared/icons.tsx` |

#### Export Pattern

All icons from the library are re-exported using a wildcard export, making them available from a single import location:

```typescript
// apps/web/src/components/shared/icons.tsx
export * from "@theexperiencecompany/gaia-icons/solid-rounded";
```

#### Importing Icons

Always import icons from the shared icons file, not directly from the package:

```tsx
// ✅ Correct: Import from shared icons
import { HomeIcon, SettingsIcon, UserIcon } from "@/components/shared/icons";

// ❌ Incorrect: Direct package import
import { HomeIcon } from "@theexperiencecompany/gaia-icons/solid-rounded";
```

This pattern ensures:
- Consistent icon usage across the codebase
- Easy access to custom icons alongside library icons
- Single source of truth for icon exports
- Simplified refactoring if the icon library changes

### IconProps Interface

All icons (both library and custom) accept a consistent set of props through the `IconProps` interface.

#### Interface Definition

```typescript
export interface IconProps extends React.SVGProps<SVGSVGElement> {
  size?: number;
  color?: string;
  strokeWidth?: number | string;
}
```

#### Props Reference

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `size` | `number` | `24` | Width and height in pixels |
| `color` | `string` | `currentColor` | Fill or stroke color |
| `strokeWidth` | `number \| string` | `2` | Stroke width for outlined icons |

#### Inherited SVG Props

Since `IconProps` extends `React.SVGProps<SVGSVGElement>`, all standard SVG attributes are also available:

- `className` — CSS classes
- `style` — Inline styles
- `onClick` — Click handler
- `aria-*` — Accessibility attributes
- `width` / `height` — Override size
- `viewBox` — SVG viewBox (usually preset)

#### Usage Examples

```tsx
// Default size (24px)
<HomeIcon />

// Custom size
<HomeIcon size={20} />

// Custom color
<SettingsIcon color="#00bbff" />

// Using currentColor (inherits from parent)
<span className="text-primary">
  <UserIcon /> {/* Inherits primary color */}
</span>

// Custom stroke width
<ChevronDown strokeWidth={1.5} />

// With className
<HomeIcon className="text-foreground-600 hover:text-foreground-900" />

// With accessibility
<SearchIcon aria-label="Search" role="img" />
```

### Custom Icons

In addition to the library icons, Gaia defines custom icons for specific use cases. These are defined in the same `icons.tsx` file and exported alongside library icons.

#### Navigation Icons

| Icon | Description | Usage |
|------|-------------|-------|
| `ChevronDown` | Downward chevron | Dropdowns, accordions |
| `ChevronUp` | Upward chevron | Collapse indicators |
| `ChevronRight` | Right chevron | Navigation, breadcrumbs |
| `ChevronLeft` | Left chevron | Back navigation |
| `ChevronsDownUp` | Double chevron (collapse) | Collapse all |
| `ChevronsUpDown` | Double chevron (expand) | Expand/sort indicators |
| `ArrowUpRight` | Diagonal arrow | External links |

#### Brand & Social Icons

| Icon | Description | Usage |
|------|-------------|-------|
| `GoogleColouredIcon` | Google logo (colored) | Google sign-in |
| `Gmail` | Gmail logo (colored) | Email integration |
| `GoogleCalendarIcon` | Google Calendar (colored) | Calendar integration |
| `Github` | GitHub logo | GitHub links, auth |
| `DiscordIcon` | Discord logo | Community links |
| `TwitterIcon` | Twitter/X logo | Social sharing |
| `WhatsappIcon` | WhatsApp logo | Share via WhatsApp |
| `YoutubeIcon` | YouTube logo | Video links |
| `LinkedinIcon` | LinkedIn logo | Professional sharing |
| `RedditIcon` | Reddit logo | Community sharing |

#### Utility Icons

| Icon | Description | Usage |
|------|-------------|-------|
| `CloudFogIcon` | Cloud with fog | Weather, loading states |
| `HeartHandIcon` | Heart in hand | Support, donations |
| `ZapIcon` | Lightning bolt | Quick actions, power features |
| `Dices` | Dice | Random, games |
| `StarFilledIcon` | Filled star | Ratings, favorites |

#### Custom Icon Structure

All custom icons follow a consistent pattern:

```tsx
export const ChevronDown = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width="24"
    height="24"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    {...props}
  >
    <title>Chevron Down</title>
    <path d="m6 9 6 6 6-6" />
  </svg>
);
```

Key characteristics:
- Default size: 24×24 pixels
- Uses `currentColor` for color inheritance
- Includes `<title>` for accessibility
- Spreads props for customization

### Icon Usage Guidelines

#### Correct Import Pattern

```tsx
// ✅ Always import from the shared icons file
import { 
  HomeIcon, 
  ChevronDown, 
  GoogleColouredIcon 
} from "@/components/shared/icons";
```

#### Sizing Recommendations

Use consistent sizes based on context:

| Context | Size | Example |
|---------|------|---------|
| **Inline with text** | 16px | `<HomeIcon size={16} />` |
| **Buttons** | 20px | `<Button><PlusIcon size={20} /> Add</Button>` |
| **Navigation** | 24px | `<NavIcon size={24} />` (default) |
| **Large displays** | 32px+ | `<FeatureIcon size={32} />` |

```tsx
// Inline with text
<p className="flex items-center gap-1">
  <InfoIcon size={16} />
  <span>Helpful tip</span>
</p>

// In a button
<button className="flex items-center gap-2">
  <PlusIcon size={20} />
  <span>Add Item</span>
</button>

// Navigation item
<a className="flex items-center gap-3">
  <HomeIcon size={24} />
  <span>Dashboard</span>
</a>

// Feature highlight
<div className="text-center">
  <ZapIcon size={48} className="text-primary mx-auto" />
  <h3>Lightning Fast</h3>
</div>
```

#### Color Inheritance with currentColor

Icons use `currentColor` by default, which means they inherit the text color from their parent element. This is the recommended approach for most cases:

```tsx
// Icon inherits text color from parent
<span className="text-primary">
  <StarFilledIcon /> {/* Will be primary color */}
</span>

// Icon inherits hover state
<button className="text-foreground-600 hover:text-foreground-900">
  <SettingsIcon /> {/* Changes color on hover */}
</button>

// Icon in a colored container
<div className="text-destructive">
  <AlertIcon /> Warning message
</div>
```

#### Explicit Color Override

When you need a specific color regardless of context:

```tsx
// Explicit color
<GoogleColouredIcon /> {/* Uses built-in brand colors */}

// Override with className
<HomeIcon className="text-primary" />

// Override with color prop
<HomeIcon color="#00bbff" />
```

#### Accessibility

Always provide accessible labels for icons, especially when used without text:

```tsx
// Icon with visible text (text provides context)
<button>
  <PlusIcon size={20} />
  <span>Add Item</span>
</button>

// Icon-only button (needs aria-label)
<button aria-label="Add item">
  <PlusIcon size={20} />
</button>

// Decorative icon (hide from screen readers)
<span aria-hidden="true">
  <StarFilledIcon />
</span>
<span>5 stars</span>
```

### Common Mistakes

Avoid these common pitfalls when using icons:

#### ❌ Don't Hardcode Colors

```tsx
// ❌ Bad: Hardcoded color won't adapt to theme
<HomeIcon color="#333333" />

// ✅ Good: Use currentColor inheritance
<span className="text-foreground-700">
  <HomeIcon />
</span>

// ✅ Good: Use Tailwind classes
<HomeIcon className="text-foreground-700" />
```

#### ❌ Don't Forget Accessibility

```tsx
// ❌ Bad: Icon-only button without label
<button>
  <CloseIcon />
</button>

// ✅ Good: Include aria-label
<button aria-label="Close dialog">
  <CloseIcon />
</button>

// ✅ Good: Include visible text
<button>
  <CloseIcon size={16} />
  <span>Close</span>
</button>
```

#### ❌ Don't Use Inconsistent Sizes

```tsx
// ❌ Bad: Random sizes throughout the UI
<nav>
  <HomeIcon size={24} />
  <SettingsIcon size={18} />
  <UserIcon size={22} />
</nav>

// ✅ Good: Consistent sizes
<nav>
  <HomeIcon size={24} />
  <SettingsIcon size={24} />
  <UserIcon size={24} />
</nav>
```

#### ❌ Don't Import Directly from Package

```tsx
// ❌ Bad: Direct package import
import { HomeIcon } from "@theexperiencecompany/gaia-icons/solid-rounded";

// ✅ Good: Import from shared icons
import { HomeIcon } from "@/components/shared/icons";
```

#### ❌ Don't Forget the Title Element

When creating custom icons, always include a `<title>` element:

```tsx
// ❌ Bad: No title
<svg viewBox="0 0 24 24">
  <path d="..." />
</svg>

// ✅ Good: Includes title
<svg viewBox="0 0 24 24">
  <title>Descriptive Icon Name</title>
  <path d="..." />
</svg>
```

### Theme-Aware Icons

Some icons (particularly brand logos that are white) need to be inverted in light mode to remain visible. Gaia provides the `icon-theme-aware` utility class for this purpose.

#### The Problem

White icons are invisible on white backgrounds in light mode:

```tsx
// ❌ White Apple logo invisible in light mode
<Image src="/apple-logo-white.svg" alt="Apple" />
```

#### The Solution

Apply the `icon-theme-aware` class to invert white icons in light mode:

```tsx
// ✅ Apple logo visible in both modes
<Image 
  src="/apple-logo-white.svg" 
  alt="Apple" 
  className="icon-theme-aware"
/>
```

#### How It Works

```css
/* Light mode: Invert white icons to black */
.icon-theme-aware {
  filter: invert(1);
}

/* Dark mode: Keep icons as-is (white on dark) */
.dark .icon-theme-aware {
  filter: invert(0);
}
```

| Mode | Filter | Result |
|------|--------|--------|
| Light | `invert(1)` | White → Black |
| Dark | `invert(0)` | White → White (unchanged) |

#### When to Use

Use `icon-theme-aware` for:
- White brand logos (Apple, etc.)
- White icons from external sources
- Any white image that needs to be visible in light mode

```tsx
// Platform icons on download page
<Image 
  src="/icons/apple-white.svg" 
  alt="iOS"
  className="object-contain icon-theme-aware"
/>

// Mobile section icons
<Image
  src="/icons/app-store-white.svg"
  alt="App Store"
  width={30}
  height={30}
  className="icon-theme-aware"
/>
```

#### When NOT to Use

Don't use `icon-theme-aware` for:
- Colored icons (they'll look wrong when inverted)
- Icons that already adapt to theme via `currentColor`
- Dark icons that are already visible in light mode

```tsx
// ❌ Don't use on colored icons
<GoogleColouredIcon className="icon-theme-aware" /> // Colors will be inverted!

// ❌ Don't use on currentColor icons
<HomeIcon className="icon-theme-aware" /> // Already adapts via currentColor
```

---

## Design Principles

### Core Principles

Gaia's design philosophy centers on creating interfaces that feel calm, focused, and effortless. These principles guide every design decision across the application.

#### 1. Clean, Minimal Aesthetic

Gaia embraces simplicity. Every element serves a purpose, and visual noise is eliminated to help users focus on what matters.

| Principle | Implementation |
|-----------|----------------|
| **Whitespace** | Generous padding and margins create breathing room |
| **Flat design** | Minimal shadows, subtle borders, no gradients |
| **Neutral palette** | Zinc-based grays with a single accent color (#00bbff) |
| **Typography hierarchy** | Clear distinction between headings, body, and metadata |

```tsx
// ✅ Clean, minimal card
<div className="bg-surface-100 rounded-lg p-6 border border-border-surface-300">
  <h3 className="text-foreground-900 font-bold">Card Title</h3>
  <p className="text-foreground-700 mt-2">Simple, focused content.</p>
</div>

// ❌ Avoid: Overly decorated
<div className="bg-gradient-to-r from-blue-500 to-purple-600 shadow-2xl rounded-3xl p-8 border-4">
  <h3 className="text-white drop-shadow-lg">Too Much</h3>
</div>
```

#### 2. Consistent Spacing and Alignment

Visual rhythm creates harmony. Gaia uses a consistent spacing scale and grid alignment throughout.

| Principle | Implementation |
|-----------|----------------|
| **4px base unit** | All spacing is a multiple of 4px |
| **Consistent gaps** | Use `gap-*` utilities for uniform spacing |
| **Alignment** | Elements align to a consistent grid |
| **Predictable patterns** | Similar components use similar spacing |

```tsx
// Consistent spacing pattern
<div className="space-y-4">
  <header className="space-y-2">
    <h1>Title</h1>
    <p>Subtitle</p>
  </header>
  <main className="space-y-4">
    {/* Content with consistent 16px gaps */}
  </main>
</div>
```

#### 3. Accessible by Default

Accessibility isn't an afterthought—it's built into every component and color choice.

| Principle | Implementation |
|-----------|----------------|
| **WCAG AA compliance** | All text meets 4.5:1 contrast ratio |
| **Keyboard navigation** | All interactive elements are focusable |
| **Screen reader support** | Semantic HTML and ARIA labels |
| **Focus indicators** | Visible focus rings on all interactive elements |

```tsx
// Accessible button with focus ring
<button 
  className="bg-primary text-primary-foreground px-4 py-2 rounded-md
             focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
>
  Accessible Action
</button>
```

#### 4. Theme-Aware Design

Every color and surface adapts seamlessly between light and dark modes without manual intervention.

| Principle | Implementation |
|-----------|----------------|
| **Semantic tokens** | Use `surface-*`, `text-foreground-*` instead of raw colors |
| **Automatic adaptation** | Colors invert appropriately per theme |
| **Consistent meaning** | `surface-100` is always "subtle elevation" regardless of theme |

```tsx
// Theme-aware component (works in both modes)
<div className="bg-surface-100 text-foreground-900 border border-border-surface-300">
  This adapts automatically to light/dark mode.
</div>
```

#### 5. Progressive Disclosure

Show only what's needed, when it's needed. Complex features reveal themselves progressively.

| Principle | Implementation |
|-----------|----------------|
| **Collapsible sections** | Accordions for secondary content |
| **Hover reveals** | Additional actions appear on hover |
| **Modal dialogs** | Complex forms in focused overlays |
| **Tooltips** | Contextual help without cluttering UI |

#### Design Principles Quick Reference

| Do | Don't |
|----|-------|
| Use semantic color tokens | Hardcode hex values |
| Maintain consistent spacing | Use arbitrary pixel values |
| Provide focus indicators | Rely only on hover states |
| Use whitespace generously | Cram elements together |
| Keep interactions predictable | Surprise users with unexpected behavior |

### Theme System

Gaia supports light and dark themes with automatic system preference detection. The theme system uses CSS class-based switching with localStorage persistence.

#### Theme Modes

| Mode | Description | CSS Class |
|------|-------------|-----------|
| `light` | Light backgrounds, dark text | No class (default) |
| `dark` | Dark backgrounds, light text | `.dark` on `<html>` |
| `system` | Follows OS preference | Resolves to `light` or `dark` |

#### How It Works

The theme is controlled by adding or removing the `.dark` class on the document root:

```html
<!-- Light mode (default) -->
<html lang="en">
  <body>...</body>
</html>

<!-- Dark mode -->
<html lang="en" class="dark">
  <body>...</body>
</html>
```

#### CSS Variable Switching

All theme-aware colors are defined as CSS variables that change based on the `.dark` class:

```css
/* Light mode (default) */
:root {
  --background: 0 0% 100%;           /* White */
  --foreground: 240 5.9% 10%;        /* Near black */
  --surface-100: 240 4.8% 95.9%;     /* Light gray */
}

/* Dark mode */
.dark {
  --background: 240 10% 3.9%;        /* Near black */
  --foreground: 240 4.8% 95.9%;      /* Near white */
  --surface-100: 240 5.9% 10%;       /* Dark gray */
}
```

#### localStorage Persistence

User theme preference is stored in localStorage under the key `gaia-theme`:

| Key | Possible Values | Description |
|-----|-----------------|-------------|
| `gaia-theme` | `"light"`, `"dark"`, `"system"` | User's theme preference |

```typescript
// Reading theme preference
const theme = localStorage.getItem("gaia-theme"); // "light" | "dark" | "system" | null

// Setting theme preference
localStorage.setItem("gaia-theme", "dark");
```

#### ThemeProvider Implementation

Gaia uses a React context provider to manage theme state:

```tsx
import { useTheme } from "@/components/providers/ThemeProvider";

function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  
  return (
    <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
      Current: {resolvedTheme}
    </button>
  );
}
```

| Hook Return | Type | Description |
|-------------|------|-------------|
| `theme` | `"light" \| "dark" \| "system"` | User's preference |
| `setTheme` | `(theme: Theme) => void` | Update preference |
| `resolvedTheme` | `"light" \| "dark"` | Actual applied theme |

#### Flash Prevention

To prevent a flash of incorrect theme on page load, Gaia injects a blocking script in the `<head>`:

```html
<script>
  (function() {
    try {
      var theme = localStorage.getItem('gaia-theme');
      if (theme === 'dark' || 
          (!theme && window.matchMedia('(prefers-color-scheme: dark)').matches) || 
          (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
      }
    } catch (e) {}
  })();
</script>
```

This runs before the page renders, ensuring the correct theme is applied immediately.

#### System Preference Detection

When theme is set to `system`, Gaia listens for OS preference changes:

```typescript
// Detect system preference
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;

// Listen for changes
window.matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", (e) => {
    if (theme === "system") {
      applyTheme(e.matches ? "dark" : "light");
    }
  });
```

#### Using Theme in Components

```tsx
// Theme-aware styling (recommended)
<div className="bg-surface-100 text-foreground-900">
  Automatically adapts to theme
</div>

// Conditional styling based on theme
<div className="bg-white dark:bg-zinc-900">
  Explicit light/dark variants
</div>

// Accessing theme in JavaScript
const { resolvedTheme } = useTheme();
const iconColor = resolvedTheme === "dark" ? "#ffffff" : "#000000";
```

#### Theme-Aware Color Tokens

Always use semantic tokens instead of raw colors:

| Instead of... | Use... |
|---------------|--------|
| `bg-white dark:bg-zinc-900` | `bg-surface-50` |
| `text-zinc-900 dark:text-zinc-50` | `text-foreground-900` |
| `border-zinc-200 dark:border-zinc-800` | `border-border-surface-300` |

### Spacing Conventions

Gaia uses Tailwind's default spacing scale, which is based on a 4px (0.25rem) unit. Consistent spacing creates visual rhythm and harmony throughout the interface.

#### Spacing Scale

| Tailwind Class | Value | Pixels | Common Use |
|----------------|-------|--------|------------|
| `*-0` | 0 | 0px | Reset spacing |
| `*-0.5` | 0.125rem | 2px | Micro adjustments |
| `*-1` | 0.25rem | 4px | Tight spacing |
| `*-1.5` | 0.375rem | 6px | Small gaps |
| `*-2` | 0.5rem | 8px | Compact elements |
| `*-2.5` | 0.625rem | 10px | Small padding |
| `*-3` | 0.75rem | 12px | Default small gap |
| `*-3.5` | 0.875rem | 14px | Medium-small |
| `*-4` | 1rem | 16px | Default padding |
| `*-5` | 1.25rem | 20px | Medium gap |
| `*-6` | 1.5rem | 24px | Section spacing |
| `*-7` | 1.75rem | 28px | Large gap |
| `*-8` | 2rem | 32px | Large padding |
| `*-9` | 2.25rem | 36px | Extra large |
| `*-10` | 2.5rem | 40px | Section margins |
| `*-12` | 3rem | 48px | Major sections |
| `*-16` | 4rem | 64px | Page sections |
| `*-20` | 5rem | 80px | Hero spacing |
| `*-24` | 6rem | 96px | Large gaps |

#### Commonly Used Spacing

| Context | Recommended Spacing | Example |
|---------|---------------------|---------|
| **Inline elements** | `gap-1` to `gap-2` | Icon + text |
| **Button padding** | `px-4 py-2` | Standard button |
| **Card padding** | `p-4` to `p-6` | Card content |
| **List items** | `space-y-2` to `space-y-4` | Vertical lists |
| **Form fields** | `space-y-4` | Form layout |
| **Section gaps** | `space-y-8` to `space-y-12` | Page sections |
| **Page margins** | `p-4` to `p-8` | Container padding |

#### Spacing Utilities

Tailwind provides utilities for all spacing needs:

| Utility | Purpose | Example |
|---------|---------|---------|
| `p-*` | Padding (all sides) | `p-4` |
| `px-*`, `py-*` | Horizontal/vertical padding | `px-4 py-2` |
| `pt-*`, `pr-*`, `pb-*`, `pl-*` | Individual sides | `pt-4` |
| `m-*` | Margin (all sides) | `m-4` |
| `mx-*`, `my-*` | Horizontal/vertical margin | `mx-auto` |
| `gap-*` | Flex/grid gap | `gap-4` |
| `space-x-*`, `space-y-*` | Child spacing | `space-y-4` |

#### Spacing Examples

```tsx
// Button with standard padding
<button className="px-4 py-2">
  Click Me
</button>

// Card with comfortable padding
<div className="p-6 space-y-4">
  <h3>Card Title</h3>
  <p>Card content with consistent internal spacing.</p>
</div>

// Form with field spacing
<form className="space-y-4">
  <div>
    <label>Email</label>
    <input className="mt-1" />
  </div>
  <div>
    <label>Password</label>
    <input className="mt-1" />
  </div>
</form>

// Navigation with icon gaps
<nav className="flex items-center gap-2">
  <HomeIcon size={20} />
  <span>Dashboard</span>
</nav>

// Page layout with section spacing
<main className="space-y-12 p-8">
  <section>Hero</section>
  <section>Features</section>
  <section>Testimonials</section>
</main>
```

#### Spacing Best Practices

| Do | Don't |
|----|-------|
| Use consistent spacing scale | Mix arbitrary values (`mt-[13px]`) |
| Use `gap-*` for flex/grid layouts | Use margins on every child |
| Use `space-y-*` for vertical lists | Manually add `mb-*` to each item |
| Keep spacing proportional | Use same spacing for all contexts |
| Use larger spacing for major sections | Cram sections together |

#### Responsive Spacing

Adjust spacing at different breakpoints:

```tsx
// Responsive padding
<div className="p-4 md:p-6 lg:p-8">
  Content with responsive padding
</div>

// Responsive gaps
<div className="grid gap-4 md:gap-6 lg:gap-8">
  Grid items
</div>
```

### Border Radius

Gaia uses a consistent border radius system based on a single `--radius` CSS variable. This creates visual harmony across all rounded elements.

#### Base Radius Variable

| Variable | Value | Description |
|----------|-------|-------------|
| `--radius` | `0.5rem` (8px) | Base border radius |

#### Radius Scale

The radius scale is derived from the base `--radius` variable:

| Token | CSS Value | Computed | Tailwind Class |
|-------|-----------|----------|----------------|
| `lg` | `var(--radius)` | 8px | `rounded-lg` |
| `md` | `calc(var(--radius) - 2px)` | 6px | `rounded-md` |
| `sm` | `calc(var(--radius) - 4px)` | 4px | `rounded-sm` |

#### CSS Variables

```css
@theme {
  --radius: 0.5rem;
  --border-radius-lg: var(--radius);
  --border-radius-md: calc(var(--radius) - 2px);
  --border-radius-sm: calc(var(--radius) - 4px);
}
```

#### Usage Guidelines

| Element | Recommended Radius | Example |
|---------|-------------------|---------|
| **Buttons** | `rounded-md` | `<button className="rounded-md">` |
| **Cards** | `rounded-lg` | `<div className="rounded-lg">` |
| **Inputs** | `rounded-md` | `<input className="rounded-md">` |
| **Badges/chips** | `rounded-full` | `<span className="rounded-full">` |
| **Avatars** | `rounded-full` | `<img className="rounded-full">` |
| **Modals/dialogs** | `rounded-lg` | `<dialog className="rounded-lg">` |
| **Tooltips** | `rounded-md` | `<div className="rounded-md">` |
| **Code blocks** | `rounded-lg` | `<pre className="rounded-lg">` |

#### Tailwind Border Radius Classes

| Class | Value | Use Case |
|-------|-------|----------|
| `rounded-none` | 0 | Sharp corners |
| `rounded-sm` | 4px | Subtle rounding |
| `rounded` | 4px | Default small |
| `rounded-md` | 6px | Buttons, inputs |
| `rounded-lg` | 8px | Cards, dialogs |
| `rounded-xl` | 12px | Large cards |
| `rounded-2xl` | 16px | Hero sections |
| `rounded-3xl` | 24px | Feature cards |
| `rounded-full` | 9999px | Circles, pills |

#### Examples

```tsx
// Button with medium radius
<button className="bg-primary text-primary-foreground px-4 py-2 rounded-md">
  Action
</button>

// Card with large radius
<div className="bg-surface-100 p-6 rounded-lg border border-border-surface-300">
  Card content
</div>

// Input with medium radius
<input 
  className="border border-input rounded-md px-3 py-2 
             focus:ring-2 focus:ring-primary"
/>

// Avatar with full radius (circle)
<img 
  src="/avatar.jpg" 
  className="size-10 rounded-full object-cover"
/>

// Badge with full radius (pill)
<span className="bg-primary/10 text-primary px-2 py-0.5 rounded-full text-sm">
  New
</span>

// Nested radius (inner elements slightly smaller)
<div className="bg-surface-100 p-4 rounded-lg">
  <div className="bg-surface-200 p-3 rounded-md">
    Nested content with smaller radius
  </div>
</div>
```

#### Customizing the Base Radius

To change the global border radius, update the `--radius` variable:

```css
:root {
  --radius: 0.75rem; /* Increase to 12px */
}
```

All derived values (`lg`, `md`, `sm`) will automatically adjust.

### Animations

Gaia uses subtle, purposeful animations to enhance user experience without being distracting. All animations are defined as CSS keyframes and exposed as Tailwind utilities.

#### Animation Variables

| Variable | Duration | Timing | Description |
|----------|----------|--------|-------------|
| `--animate-accordion-down` | 0.2s | ease-out | Accordion expand |
| `--animate-accordion-up` | 0.2s | ease-out | Accordion collapse |
| `--animate-scale-in` | 0.4s | ease-out | Element entrance |
| `--animate-shimmer` | 2s | linear | Loading shimmer |
| `--animate-shine` | 5s | linear | Shine effect |
| `--animate-shiny-text` | 8s | — | Text shine |
| `--animate-shake` | 0.7s | ease-in-out | Error shake |
| `--animate-orbit` | variable | linear | Orbital motion |
| `--animate-grid` | 15s | linear | Grid animation |

#### Accordion Animations

Used for expandable/collapsible content sections:

```css
@keyframes accordion-down {
  from { height: 0; }
  to { height: var(--radix-accordion-content-height); }
}

@keyframes accordion-up {
  from { height: var(--radix-accordion-content-height); }
  to { height: 0; }
}
```

```tsx
// Accordion component usage
<AccordionContent className="animate-accordion-down">
  Expandable content
</AccordionContent>
```

#### Scale-In Animation

A smooth entrance animation for elements appearing on screen:

```css
@keyframes scale-in {
  0% {
    transform: scale(0.9);
    opacity: 0;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
```

```tsx
// Element entrance
<div className="animate-scale-in">
  This element scales in smoothly
</div>

// With blur variant (from globals.css)
<div className="animate-scale-in-blur">
  Scales in with blur effect
</div>
```

#### Shimmer Animation

A loading state animation that creates a moving highlight effect:

```css
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
```

```tsx
// Skeleton loading state
<div className="relative overflow-hidden bg-surface-200 rounded-md">
  <div className="absolute inset-0 animate-shimmer bg-gradient-to-r from-transparent via-surface-100 to-transparent" />
</div>
```

#### Shine Effect

A continuous shine animation for decorative elements:

```css
@keyframes shine {
  0% { background-position: 100%; }
  100% { background-position: -100%; }
}
```

```tsx
// Shiny button or badge
<button className="animate-shine bg-gradient-to-r from-primary via-primary/50 to-primary bg-[length:200%_100%]">
  Premium Feature
</button>
```

#### Shake Animation

Used for error feedback or attention-grabbing:

```css
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  10%, 30%, 50%, 70%, 90% { transform: translateX(-4px); }
  20%, 40%, 60%, 80% { transform: translateX(4px); }
}
```

```tsx
// Error shake on invalid input
<input 
  className={cn("border rounded-md", hasError && "animate-shake border-destructive")}
/>
```

#### Shiny Text Animation

A text highlight effect that moves across the text:

```css
@keyframes shiny-text {
  0%, 90%, 100% {
    background-position: calc(-100% - var(--shiny-width)) 0;
  }
  30%, 60% {
    background-position: calc(100% + var(--shiny-width)) 0;
  }
}
```

```tsx
// Shiny text effect
<span 
  className="animate-shiny-text bg-clip-text text-transparent 
             bg-gradient-to-r from-foreground-900 via-primary to-foreground-900
             bg-[length:200%_100%]"
  style={{ "--shiny-width": "100px" } as React.CSSProperties}
>
  Highlighted Text
</span>
```

#### Marquee Animations

For scrolling content like testimonials or logos:

```css
@keyframes marquee {
  from { transform: translateX(0); }
  to { transform: translateX(calc(-100% - var(--gap))); }
}

@keyframes marquee-vertical {
  from { transform: translateY(0); }
  to { transform: translateY(calc(-100% - var(--gap))); }
}
```

```tsx
// Horizontal marquee
<div 
  className="animate-marquee flex gap-4"
  style={{ "--duration": "20s", "--gap": "1rem" } as React.CSSProperties}
>
  {/* Scrolling content */}
</div>
```

#### Animation Best Practices

| Do | Don't |
|----|-------|
| Use subtle, quick animations (0.2-0.4s) | Use long, distracting animations |
| Animate opacity and transform | Animate layout properties (width, height) |
| Provide reduced-motion alternatives | Force animations on all users |
| Use animations for feedback | Animate purely for decoration |
| Keep animations consistent | Mix different animation styles |

#### Reduced Motion Support

Always respect user preferences for reduced motion:

```tsx
// Conditional animation
<div className="motion-safe:animate-scale-in motion-reduce:opacity-100">
  Respects user preference
</div>
```

```css
/* In CSS */
@media (prefers-reduced-motion: reduce) {
  .animate-scale-in {
    animation: none;
    opacity: 1;
  }
}
```

#### Transition Utilities

For simple state changes, use Tailwind's transition utilities instead of keyframe animations:

```tsx
// Hover transition
<button className="transition-colors hover:bg-primary/90">
  Smooth hover
</button>

// Multiple properties
<div className="transition-all duration-200 hover:scale-105 hover:shadow-lg">
  Hover effect
</div>

// Custom duration
<div className="transition-opacity duration-300">
  Fade effect
</div>
```

| Utility | Properties | Duration |
|---------|------------|----------|
| `transition` | All | 150ms |
| `transition-colors` | Color properties | 150ms |
| `transition-opacity` | Opacity | 150ms |
| `transition-transform` | Transform | 150ms |
| `transition-all` | All properties | 150ms |
| `duration-*` | — | Custom duration |

---

## Utilities

### Font Access

Gaia uses Next.js font optimization (`next/font/google`) to load fonts efficiently. This approach provides automatic self-hosting, zero layout shift, and optimal performance.

#### Google Fonts Links

For design tools or external applications, you can access the fonts directly from Google Fonts:

| Font | Google Fonts Link | Download |
|------|-------------------|----------|
| **Inter** | [fonts.google.com/specimen/Inter](https://fonts.google.com/specimen/Inter) | [Download](https://fonts.google.com/download?family=Inter) |
| **Instrument Serif** | [fonts.google.com/specimen/Instrument+Serif](https://fonts.google.com/specimen/Instrument+Serif) | [Download](https://fonts.google.com/download?family=Instrument+Serif) |
| **Anonymous Pro** | [fonts.google.com/specimen/Anonymous+Pro](https://fonts.google.com/specimen/Anonymous+Pro) | [Download](https://fonts.google.com/download?family=Anonymous+Pro) |

#### Next.js Font Optimization Setup

Gaia's fonts are configured in `apps/web/src/app/fonts/` using Next.js's built-in font optimization.

**Font Configuration Files:**

| File | Font | Purpose |
|------|------|---------|
| `inter.ts` | Inter | Primary body font |
| `instrument-serif.ts` | Instrument Serif | Display/accent font |
| `anonymous-pro.ts` | Anonymous Pro | Monospace/code font |
| `index.ts` | — | Exports and helpers |

**Inter Configuration:**

```typescript
// apps/web/src/app/fonts/inter.ts
import { Inter } from "next/font/google";

export const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
  preload: true,
});
```

**Instrument Serif Configuration:**

```typescript
// apps/web/src/app/fonts/instrument-serif.ts
import { Instrument_Serif } from "next/font/google";

export const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400", // Instrument Serif only has one weight
  variable: "--font-instrument-serif",
  display: "swap",
  preload: true,
  style: "normal",
});
```

**Anonymous Pro Configuration:**

```typescript
// apps/web/src/app/fonts/anonymous-pro.ts
import { Anonymous_Pro } from "next/font/google";

export const anonymousPro = Anonymous_Pro({
  subsets: ["latin"],
  weight: ["400", "700"],
  style: ["normal", "italic"],
  variable: "--font-anonymous-pro",
  display: "swap",
  preload: true,
});
```

**Font Index and Helpers:**

```typescript
// apps/web/src/app/fonts/index.ts
import { anonymousPro } from "./anonymous-pro";
import { instrumentSerif } from "./instrument-serif";
import { inter } from "./inter";

// Export fonts
export { anonymousPro, instrumentSerif, inter };

// Set Inter as the default font
export const defaultFont = inter;
export const defaultTextFont = inter;
export const defaultMonoFont = anonymousPro;

// Helper function to get all font CSS variables
export function getAllFontVariables() {
  return `${inter.variable} ${instrumentSerif.variable} ${anonymousPro.variable}`;
}
```

**Loading Fonts in Layout:**

```tsx
// apps/web/src/app/layout.tsx
import { getAllFontVariables } from "./fonts";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={getAllFontVariables()}>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
```

**CSS Variable Mapping:**

Once loaded, the fonts are available via CSS variables and Tailwind classes:

| CSS Variable | Tailwind Class | Font |
|--------------|----------------|------|
| `--font-inter` | `font-sans` | Inter |
| `--font-instrument-serif` | `font-serif` | Instrument Serif |
| `--font-anonymous-pro` | `font-mono` | Anonymous Pro |

**Tailwind Configuration:**

```css
/* apps/web/src/app/styles/tailwind.css */
@theme {
  --font-sans: var(--font-inter), system-ui, sans-serif;
  --font-serif: var(--font-instrument-serif), serif;
  --font-mono:
    var(--font-anonymous-pro), ui-monospace, "Cascadia Code", "Source Code Pro",
    Menlo, Consolas, "DejaVu Sans Mono", monospace;
}
```

### shadcn/ui Configuration

Gaia uses [shadcn/ui](https://ui.shadcn.com) as the foundation for its component library. shadcn/ui provides beautifully designed, accessible components that you can copy and customize.

#### Configuration File

The shadcn/ui configuration is stored in `apps/web/components.json`:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.js",
    "css": "src/app/styles/tailwind.css",
    "baseColor": "zinc",
    "cssVariables": true,
    "prefix": ""
  },
  "iconLibrary": "lucide",
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  },
  "registries": {
    "@magicui": "https://magicui.design/r/{name}.json"
  }
}
```

#### Configuration Details

| Setting | Value | Description |
|---------|-------|-------------|
| **Style** | `new-york` | Uses the "New York" style variant (more refined, subtle) |
| **RSC** | `true` | React Server Components enabled |
| **TSX** | `true` | TypeScript with JSX |
| **Base Color** | `zinc` | Zinc color palette as the neutral base |
| **CSS Variables** | `true` | Uses CSS variables for theming |
| **Prefix** | `""` | No prefix for utility classes |

#### Icon Library Note

> **Important:** While shadcn/ui is configured with `lucide` as the icon library, Gaia uses a custom icon library (`@theexperiencecompany/gaia-icons`) for consistency. See the [Icons](#icons) section for details.

When adding new shadcn/ui components, replace Lucide icons with Gaia icons:

```tsx
// ❌ Don't use Lucide icons from shadcn/ui
import { ChevronDown } from "lucide-react";

// ✅ Use Gaia icons instead
import { ChevronDown } from "@/components/shared/icons";
```

#### Path Aliases

| Alias | Path | Usage |
|-------|------|-------|
| `@/components` | `src/components` | All components |
| `@/components/ui` | `src/components/ui` | shadcn/ui components |
| `@/lib` | `src/lib` | Utility libraries |
| `@/lib/utils` | `src/lib/utils` | `cn()` helper and utilities |
| `@/hooks` | `src/hooks` | Custom React hooks |

#### Adding New Components

To add a new shadcn/ui component:

```bash
# From the apps/web directory
npx shadcn@latest add button
npx shadcn@latest add dialog
npx shadcn@latest add dropdown-menu
```

Components are installed to `apps/web/src/components/ui/`.

#### Magic UI Registry

Gaia also has access to [Magic UI](https://magicui.design) components via the registry:

```bash
# Add Magic UI components
npx shadcn@latest add "@magicui/shimmer-button"
```

#### The `cn()` Utility

shadcn/ui uses a `cn()` utility for merging Tailwind classes. It's located at `apps/web/src/lib/utils.ts`:

```typescript
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

**Usage:**

```tsx
import { cn } from "@/lib/utils";

// Merge conditional classes
<button className={cn(
  "px-4 py-2 rounded-md",
  isActive && "bg-primary text-primary-foreground",
  isDisabled && "opacity-50 cursor-not-allowed"
)}>
  Click me
</button>
```

### HeroUI Integration

[HeroUI](https://www.heroui.com) (formerly NextUI) provides additional React components with built-in accessibility and beautiful animations. Gaia integrates HeroUI alongside shadcn/ui for a comprehensive component library.

#### Installation

HeroUI is installed as a dependency:

```bash
npm install @heroui/react @heroui/system @heroui/theme
```

#### Provider Setup

HeroUI requires a provider wrapper for routing integration. This is configured in `apps/web/src/layouts/HeroUIProvider.tsx`:

```tsx
// apps/web/src/layouts/HeroUIProvider.tsx
"use client";

import { HeroUIProvider as HeroUIProviderComponent } from "@heroui/system";
import { useRouter } from "next/navigation";

// TypeScript router configuration
declare module "@react-types/shared" {
  interface RouterConfig {
    routerOptions: NonNullable<
      Parameters<ReturnType<typeof useRouter>["push"]>[1]
    >;
  }
}

export function HeroUIProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  return (
    <HeroUIProviderComponent navigate={router.push}>
      {children}
    </HeroUIProviderComponent>
  );
}
```

**Provider Hierarchy:**

```tsx
// apps/web/src/layouts/ProvidersLayout.tsx
import { HeroUIProvider } from "@/layouts/HeroUIProvider";

export function ProvidersLayout({ children }) {
  return (
    <HeroUIProvider>
      <QueryProvider>
        {/* Other providers */}
        {children}
      </QueryProvider>
    </HeroUIProvider>
  );
}
```

#### Theme Configuration

HeroUI's theme is configured via a Tailwind plugin in `apps/web/src/app/styles/hero.ts`:

```typescript
// apps/web/src/app/styles/hero.ts
import { heroui } from "@heroui/theme";

export default heroui({
  themes: {
    light: {
      colors: {
        background: "#ffffff",
        foreground: "#18181b",
        default: {
          50: "#fafafa",
          100: "#f4f4f5",
          200: "#e4e4e7",
          300: "#d4d4d8",
          400: "#a1a1aa",
          500: "#71717a",
          600: "#52525b",
          700: "#3f3f46",
          800: "#27272a",
          900: "#18181b",
          DEFAULT: "#f4f4f5",
          foreground: "#18181b",
        },
        content1: "#ffffff",
        content2: "#fafafa",
        content3: "#f4f4f5",
        content4: "#e4e4e7",
      },
    },
    dark: {
      colors: {
        background: "#09090b",
        foreground: "#fafafa",
        default: {
          50: "#18181b",
          100: "#27272a",
          200: "#3f3f46",
          300: "#52525b",
          400: "#71717a",
          500: "#a1a1aa",
          600: "#d4d4d8",
          700: "#e4e4e7",
          800: "#f4f4f5",
          900: "#fafafa",
          DEFAULT: "#3f3f46",
          foreground: "#fafafa",
        },
        content1: "#18181b",
        content2: "#27272a",
        content3: "#3f3f46",
        content4: "#52525b",
      },
    },
  },
});
```

**Loading the Plugin:**

```css
/* apps/web/src/app/styles/tailwind.css */
@import "tailwindcss";

/* HeroUI theme source */
@source "../../../../../node_modules/@heroui/theme/dist/**/*.{js,ts,jsx,tsx}";

/* Load HeroUI plugin */
@plugin "./hero.ts";
```

#### Theme Variables

HeroUI theme variables are defined alongside Gaia's design tokens:

```css
:root {
  /* HeroUI theme variables */
  --heroui-primary: #00bbff;
  --heroui-primary-foreground: #000000;
  --heroui-white: #ffffff;
  --heroui-white-foreground: #000000;
}

.dark {
  /* Same values in dark mode */
  --heroui-primary: #00bbff;
  --heroui-primary-foreground: #000000;
  --heroui-white: #ffffff;
  --heroui-white-foreground: #000000;
}
```

#### HeroUI Color Mapping

| HeroUI Variable | Value | Gaia Equivalent |
|-----------------|-------|-----------------|
| `--heroui-primary` | `#00bbff` | `--primary` |
| `--heroui-primary-foreground` | `#000000` | `--primary-foreground` |
| `--heroui-white` | `#ffffff` | `--color-white` |
| `--heroui-white-foreground` | `#000000` | `--color-white-foreground` |

#### Content Layers

HeroUI uses content layers for elevated surfaces:

| Layer | Light Mode | Dark Mode | Use Case |
|-------|------------|-----------|----------|
| `content1` | `#ffffff` | `#18181b` | Primary content area |
| `content2` | `#fafafa` | `#27272a` | Secondary elevation |
| `content3` | `#f4f4f5` | `#3f3f46` | Tertiary elevation |
| `content4` | `#e4e4e7` | `#52525b` | Quaternary elevation |

#### Using HeroUI Components

```tsx
import { Button, Input, Modal, ModalContent, ModalHeader, ModalBody } from "@heroui/react";

// Button example
<Button color="primary" variant="solid">
  Get Started
</Button>

// Input example
<Input
  label="Email"
  placeholder="Enter your email"
  variant="bordered"
/>

// Modal example
<Modal isOpen={isOpen} onClose={onClose}>
  <ModalContent>
    <ModalHeader>Modal Title</ModalHeader>
    <ModalBody>
      Modal content goes here.
    </ModalBody>
  </ModalContent>
</Modal>
```

#### When to Use HeroUI vs shadcn/ui

| Use Case | Recommended Library |
|----------|---------------------|
| Basic buttons, inputs, dialogs | shadcn/ui |
| Complex data tables | HeroUI |
| Animated modals | HeroUI |
| Dropdowns, popovers | shadcn/ui (Radix-based) |
| Autocomplete, select | HeroUI |
| Tabs, accordions | shadcn/ui |
| Tooltips | shadcn/ui |
| Date pickers | HeroUI |

> **Tip:** When in doubt, check if a shadcn/ui component exists first. Use HeroUI for components that benefit from its built-in animations and more complex interactions.

#### External Documentation

| Resource | Link |
|----------|------|
| HeroUI Documentation | [heroui.com](https://www.heroui.com) |
| HeroUI Components | [heroui.com/docs/components](https://www.heroui.com/docs/components) |
| HeroUI Theme | [heroui.com/docs/customization/theme](https://www.heroui.com/docs/customization/theme) |
| shadcn/ui Documentation | [ui.shadcn.com](https://ui.shadcn.com) |
| Tailwind CSS | [tailwindcss.com/docs](https://tailwindcss.com/docs) |

---

## Component Patterns

This section documents the core UI component patterns used throughout Gaia. All components are built on top of [shadcn/ui](https://ui.shadcn.com) with custom styling to match Gaia's design system.

### Buttons

Buttons are the primary interactive elements for triggering actions. Gaia's button component uses [class-variance-authority](https://cva.style/docs) (CVA) for variant management and supports composition via Radix UI's `Slot` component.

#### Import

```tsx
import { Button, buttonVariants } from "@/components/ui/button";
```

#### Button Variants

| Variant | Description | Use Case |
|---------|-------------|----------|
| `default` | Primary brand color with shadow | Primary actions, CTAs |
| `destructive` | Red/danger color | Delete, remove, destructive actions |
| `outline` | Bordered with transparent background | Secondary actions, cancel buttons |
| `secondary` | Muted background color | Alternative secondary actions |
| `ghost` | No background, hover reveals accent | Toolbar buttons, icon buttons |
| `link` | Text-only with underline on hover | Inline links, navigation |

#### Variant Styling Details

**Default (Primary)**
```css
bg-primary text-primary-foreground shadow-xs hover:bg-primary/90
```

**Destructive**
```css
bg-destructive text-white shadow-xs hover:bg-destructive/90
focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40
dark:bg-destructive/60
```

**Outline**
```css
border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground
dark:bg-input/30 dark:border-input dark:hover:bg-input/50
```

**Secondary**
```css
bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80
```

**Ghost**
```css
hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50
```

**Link**
```css
text-primary underline-offset-4 hover:underline
```

#### Button Sizes

| Size | Height | Padding | Use Case |
|------|--------|---------|----------|
| `default` | `h-9` (36px) | `px-4 py-2` | Standard buttons |
| `sm` | `h-8` (32px) | `px-3` | Compact UI, tables |
| `lg` | `h-10` (40px) | `px-6` | Hero sections, prominent CTAs |
| `icon` | `size-9` (36x36px) | — | Icon-only buttons |

#### Size Styling Details

```css
/* Default */
h-9 px-4 py-2 has-[>svg]:px-3

/* Small */
h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5

/* Large */
h-10 rounded-md px-6 has-[>svg]:px-4

/* Icon */
size-9
```

> **Note:** Buttons with SVG icons automatically adjust padding via the `has-[>svg]` selector.

#### Base Styles

All buttons share these base styles:

```css
inline-flex items-center justify-center gap-2 whitespace-nowrap
rounded-md text-sm font-medium transition-all cursor-pointer
disabled:pointer-events-none disabled:opacity-50
[&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4
shrink-0 [&_svg]:shrink-0 outline-none
```

#### Focus States

Buttons use a consistent focus ring pattern:

```css
focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]
```

For invalid/error states:

```css
aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40
aria-invalid:border-destructive
```

#### Code Examples

**Basic Usage**

```tsx
// Primary button (default)
<Button>Get Started</Button>

// With variant
<Button variant="destructive">Delete Account</Button>
<Button variant="outline">Cancel</Button>
<Button variant="secondary">Save Draft</Button>
<Button variant="ghost">More Options</Button>
<Button variant="link">Learn more</Button>
```

**With Sizes**

```tsx
// Size variants
<Button size="sm">Small</Button>
<Button size="default">Default</Button>
<Button size="lg">Large</Button>
<Button size="icon"><SearchIcon /></Button>
```

**With Icons**

```tsx
// Icon with text
<Button>
  <PlusIcon />
  Add Item
</Button>

// Icon-only button
<Button variant="ghost" size="icon">
  <SettingsIcon />
  <span className="sr-only">Settings</span>
</Button>

// Icon on the right
<Button>
  Continue
  <ArrowRightIcon />
</Button>
```

**As Child (Composition)**

Use `asChild` to render the button styles on a different element:

```tsx
// As a link
<Button asChild>
  <a href="/dashboard">Go to Dashboard</a>
</Button>

// With Next.js Link
<Button asChild variant="outline">
  <Link href="/settings">Settings</Link>
</Button>
```

**Disabled State**

```tsx
<Button disabled>Processing...</Button>
<Button variant="destructive" disabled>Cannot Delete</Button>
```

**Loading State**

```tsx
<Button disabled>
  <Spinner className="animate-spin" />
  Loading...
</Button>
```

#### Using buttonVariants

For non-button elements that need button styling:

```tsx
import { buttonVariants } from "@/components/ui/button";
import Link from "next/link";

// Apply button styles to a link
<Link 
  href="/signup" 
  className={buttonVariants({ variant: "default", size: "lg" })}
>
  Sign Up
</Link>

// With custom classes
<a 
  href="/docs" 
  className={buttonVariants({ variant: "outline", className: "mt-4" })}
>
  Documentation
</a>
```

#### Complete Button Component Reference

```tsx
// Full component signature
interface ButtonProps extends React.ComponentProps<"button"> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "icon";
  asChild?: boolean;
}

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }), "cursor-pointer")}
      {...props}
    />
  );
}
```

#### Accessibility

- Buttons automatically receive `cursor-pointer` for visual feedback
- Disabled buttons have `pointer-events-none` and reduced opacity
- Focus states use visible ring indicators for keyboard navigation
- Icon-only buttons should include `sr-only` text for screen readers
- Use semantic `<button>` elements; use `asChild` for links that look like buttons

#### Best Practices

| Do | Don't |
|----|-------|
| Use `default` for primary actions | Use multiple primary buttons in one view |
| Use `destructive` for irreversible actions | Use `destructive` for cancel buttons |
| Use `outline` or `ghost` for secondary actions | Mix too many variants in one area |
| Include loading states for async actions | Leave users without feedback |
| Use `size="icon"` for icon-only buttons | Forget accessible labels for icon buttons |

### Form Inputs

<!-- TODO: Task 11.2 - Document form input patterns -->

### Dialogs

<!-- TODO: Task 11.3 - Document dialog patterns -->

### Sidebar

<!-- TODO: Task 11.4 - Document sidebar patterns -->
