# UI Consistency Report

## Summary
- Components audited: 35
- Mandatory violations: 2
- Quality recommendations: 1

---

## Mandatory Violations (must fix)

### 1. AlertBanner — wrong outer background
```
Component: AlertBannerView
Line: 1481
Violation type: Mandatory
Issue: <div className={`rounded-2xl p-4 ${style.bg}`}>
       Outer container uses the status color (e.g. bg-blue-400/10) as its background
       instead of the required bg-zinc-800.
Fix: <div className="rounded-2xl bg-zinc-800 p-4">
     Move the status color to an inner badge/accent element, not the outer card shell.
```

### 2. AlertBanner — wrong header text color
```
Component: AlertBannerView
Line: 1482
Violation type: Mandatory
Issue: <p className={`text-sm font-semibold ${style.text}`}>{props.title}</p>
       Card title uses the status color (e.g. text-blue-400) instead of text-zinc-100.
Fix: <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
     Description text should carry the accent color as it already does via style.accent.
```

---

## Quality Recommendations (should fix)

### 1. DiffBlock — bare `rounded` on diff line rows
```
Component: DiffBlockView
Line: 1190
Violation type: Quality
Issue: className={`px-2 py-0.5 rounded text-xs font-mono ...`}
       Uses bare `rounded` (which resolves to rounded-md) on individual diff line rows.
       The style guide says rounded-2xl is the only radius value to use.
Fix: Change `rounded` to `rounded-2xl` for full consistency.
     (These are very small rows so rounded-2xl may look slightly bulbous — acceptable
     trade-off vs inconsistency; alternatively omit the radius class entirely since the
     row has no background of its own to clip.)
```

---

## Passing Components

The following 33 components passed all mandatory checks with no violations:

1. DataCard
2. ResultList
3. DataTable
4. ComparisonTable
5. StatusCard
6. ActionCard
7. TagGroup
8. FileTree
9. Accordion
10. TabsBlock
11. ProgressList
12. StatRow
13. SelectableList
14. AvatarList
15. KbdBlock
16. MetricCard
17. BarChart
18. LineChart
19. AreaChart
20. PieChart
21. ScatterChart
22. RadarChart
23. GaugeChart
24. ImageBlock
25. ImageGallery
26. VideoBlock
27. AudioPlayer
28. DiffBlock (quality note only)
29. MapBlock
30. CalendarMini
31. NumberTicker
32. Carousel
33. TreeView
34. Timeline
35. JsonViewer
36. Steps

(AlertBanner is the only component with mandatory violations.)
