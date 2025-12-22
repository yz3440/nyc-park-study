# Triangle Labeling Tool

A web-based tool for manually labeling NYC park polygons to classify their triangularity.

## Overview

This tool provides a full-screen map interface to visually inspect each park's polygon shape and assign one of four triangle classification labels:

- **Definitely Triangle** - The shape is clearly a triangle
- **Most Likely a Triangle** - The shape appears to be a triangle with minor deviations
- **Somewhat a Triangle** - The shape has triangular characteristics but isn't definitively one
- **Not Triangle** - The shape is not a triangle

## Setup

### 1. Environment Variables

Copy the example env file and add your Mapbox token:

```bash
cp .env.example .env
```

Edit `.env` and add your Mapbox access token. You can get one at [Mapbox](https://account.mapbox.com/access-tokens/).

Alternatively, if you have a `.env` file in the parent directory with `MAPBOX_ACCESS_TOKEN`, it will be used automatically.

### 2. Initialize the Database

Run the initialization script to create the SQLite database from the source GeoJSON:

```bash
cd triangle_labeling_tool
uv run 1_init_db.py
```

This will:
- Read from `../source_data/Parks_Properties_20251119_modified.geojson`
- Create `triangle_labels.db` with all park properties and geometry
- If the database already exists with data, you'll be prompted to confirm overwrite

### 3. Start the Labeling Tool

Launch the web server:

```bash
uv run 2_labeling_tool.py
```

Then open http://localhost:8000 in your browser.

## UI Features

### Full-Screen Map View
- Park polygon displayed in transparent red
- Instant map transitions (no animation delay)
- Auto-zoom to park bounding box

### Floating Control Panel (Top Left)
- Stats: Total parks, labeled count, remaining count
- Current park info: Name, type, borough, acreage
- Label buttons with keyboard shortcuts
- Navigation: Random Next, Next Unlabeled
- Collapsible park list for browsing

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Definitely Triangle (auto-saves & next) |
| `2` | Most Likely a Triangle (opens notes popup) |
| `3` | Somewhat a Triangle (opens notes popup) |
| `4` | Not Triangle (auto-saves & next) |
| `N` | Random unlabeled park |
| `→` | Next unlabeled park (by ID) |
| `L` | Toggle park list visibility |

### Notes Popup
When labeling a park as "Most Likely" or "Somewhat", a popup window opens to:
- Select from existing notes used previously
- Enter a custom note
- Save & Next (Enter) or Skip Note (Esc)

## Export Labels

After labeling, export the data back to GeoJSON:

```bash
uv run 3_export_geojson.py
```

This creates:
- `../output_data/parks_with_triangle_labels.geojson` - All parks with label fields
- `../output_data/parks_labeled_triangles_only.geojson` - Only labeled parks

The exported GeoJSON includes two new fields:
- `main_triangle_label` - The assigned label
- `triangle_note` - Optional notes

## Database Schema

The SQLite database (`triangle_labels.db`) contains a single `parks` table with:
- All original GeoJSON properties
- `geometry` - Stored as GeoJSON string
- `main_triangle_label` - Label assigned by user
- `triangle_note` - Optional notes
- `labeled_at` - Timestamp when labeled

## File Structure

```
triangle_labeling_tool/
├── 1_init_db.py          # Initialize database
├── 2_labeling_tool.py    # FastAPI web server
├── 3_export_geojson.py   # Export to GeoJSON
├── triangle_labels.db    # SQLite database (created by init)
├── .env                  # Your Mapbox token (create from .env.example)
├── .env.example          # Example env file
└── README.md             # This file
```

## API Endpoints

The FastAPI server exposes these endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main labeling UI (full-screen map) |
| GET | `/notes` | Notes input popup |
| GET | `/api/parks` | List parks with pagination |
| GET | `/api/parks/{id}` | Get single park |
| POST | `/api/parks/{id}/label` | Update park label |
| GET | `/api/stats` | Get labeling statistics |
| GET | `/api/next-unlabeled` | Get next unlabeled park ID |
| GET | `/api/random-unlabeled` | Get random unlabeled park ID |
| GET | `/api/notes` | Get existing notes for reuse |
