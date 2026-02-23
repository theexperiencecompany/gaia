---
name: maps-errand-planner
description: Plan an efficient route for multiple errands and set reminders.
target: any
---

# Maps: Errand Planner

## When to Activate
User says "I need to go to the [Place 1], [Place 2], and [Place 3]. What's the best route?", "Plan my errands for today", or "Help me plan my shopping trip".

## Step 1: Resolve Locations

**Search for each destination:**
```
GOOGLEMAPS_SEARCH_PLACES(query="[Place 1]")
GOOGLEMAPS_SEARCH_PLACES(query="[Place 2]")
GOOGLEMAPS_SEARCH_PLACES(query="[Place 3]")
```

**Extract coordinates or Place IDs.**

## Step 2: Calculate Travel Times

**Get the distance matrix:**
```
GOOGLEMAPS_GET_DISTANCE_MATRIX(
  origins=["[Current Location]"],
  destinations=["[Loc 1]", "[Loc 2]", "[Loc 3]"],
  travel_mode="driving"
)
```

## Step 3: Optimize the Route

**Analyze metrics:**
- Compare travel times and distances.
- Consider opening hours (if returned by `GOOGLEMAPS_GET_PLACE_DETAILS`).
- Suggest the most efficient sequence (e.g., "Start at [Bank] because it closes early, then head to [Grocery Store]").

## Step 4: Set Reminders

**Add tasks to Todoist:**
```
TODOIST_CREATE_TASK(
  content="Visit [Place 1]",
  description="Errand 1 of 3: [Address]",
  due_string="today"
)
```

## Step 5: Summary Report
"I've planned your route!
1. Start at [Place 1] (10 mins away)
2. Then [Place 2] (5 mins from 1)
3. Finish at [Place 3] (8 mins from 2)
Total travel time: approx 23 mins. I've added these to your Todoist."

## Tools Used
- **Google Maps**: `GOOGLEMAPS_SEARCH_PLACES`, `GOOGLEMAPS_GET_DISTANCE_MATRIX`, `GOOGLEMAPS_GET_PLACE_DETAILS`
- **Todoist**: `TODOIST_CREATE_TASK`, `TODOIST_LIST_PROJECTS`

## Anti-Patterns
- Listing directions without considering the total trip time
- Not verifying if locations are currently open
- Forgetting to include the starting location in the matrix
