# `data/seed/` — registry seed data

The agent reasons over three MongoDB collections. This directory holds the
**seed JSON** that's loaded into MongoDB at first run.

## Files

| File                  | Collection           | What it is                                  |
|-----------------------|----------------------|---------------------------------------------|
| `seed/mower_models.json` | `mower_models`    | Curated catalog of real robotic mowers     |
| `seed/yards.json`        | `yards`           | Sample yard archetypes for retrieval       |
| `seed/deployment_plans.json` | `deployment_plans` | A few historical example plans         |

## Schema

### `mower_models`
```json
{
  "_id": "husqvarna-automower-450x",
  "brand": "Husqvarna",
  "model": "Automower 450X",
  "year": 2024,
  "max_yard_area_sqm": 5000,
  "max_slope_pct": 45,
  "obstacle_handling": "ultrasonic + bumper",
  "boundary_tech": "wire",
  "charging": "auto-dock",
  "price_tier": "premium",
  "source_url": "https://www.husqvarna.com/..."
}
```

### `yards`
```json
{
  "_id": "yard-suburban-flat-small",
  "area_sqm": 320,
  "slope_pct": 4,
  "obstacles": ["tree", "flowerbed"],
  "boundary_type": "fenced",
  "charging_access": "outlet-near",
  "terrain": "flat-grass"
}
```

### `deployment_plans`
```json
{
  "_id": "plan-001",
  "yard_id": "yard-suburban-flat-small",
  "mower_id": "husqvarna-automower-450x",
  "created_at": "2026-05-28T10:00:00Z",
  "fit_reasons": [
    "yard area within mower max (320 < 5000 sqm)",
    "slope well within range (4 < 45 pct)",
    "wire boundary supported"
  ],
  "plan": {
    "boundary_placement": "perimeter wire 30 cm in from fence, with islands around trees",
    "dock_location": "north-east corner, near outdoor outlet",
    "first_mow_zones": [
      {"zone": "main lawn", "priority": 1},
      {"zone": "side strip", "priority": 2}
    ],
    "schedule": "Mon-Wed-Fri 06:00–08:00"
  }
}
```

## Sourcing notes

- Use manufacturer spec sheets and product pages where possible — drop the URL
  into `source_url` so the recommendation can be audited.
- Where a spec is missing, leave the field `null` (not 0, not ""), and add a
  short note in `assumptions.md` (create it if it doesn't exist).
- The yard archetypes don't need to be real backyards — they need to be
  *diverse*: cover the corner cases (steep, complex, narrow, fenced, rural).

## Loading into MongoDB

Once Mongo Atlas is up, seeding is one command (script lands in `agent/`):
```bash
python agent/src/seed_db.py
```
