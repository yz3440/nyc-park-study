#!/usr/bin/env python3
"""
Triangle Labeling Tool - Web UI for labeling park polygons as triangles.
Uses FastAPI for the backend and serves a static HTML page with Mapbox.
"""

import json
import os
import random
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Load environment variables from local .env or parent .env
env_path = Path(__file__).parent / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

MAPBOX_ACCESS_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN", "")
if not MAPBOX_ACCESS_TOKEN:
    print("WARNING: MAPBOX_ACCESS_TOKEN not found in environment variables!")

DB_PATH = Path(__file__).parent / "triangle_labels.db"

app = FastAPI(title="Triangle Labeling Tool", version="1.0.0")


# Pydantic models
class LabelUpdate(BaseModel):
    park_id: int
    main_triangle_label: str
    triangle_note: Optional[str] = None


class ParkResponse(BaseModel):
    id: int
    source_id: str
    signname: str
    name311: str
    typecategory: str
    subcategory: str
    borough: str
    acres: str
    geometry: dict
    main_triangle_label: Optional[str]
    triangle_note: Optional[str]


# Database helper
def get_db():
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=500, detail="Database not found. Run 1_init_db.py first."
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/parks")
def get_parks(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    filter_label: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Get parks with pagination and optional filtering."""
    conn = get_db()
    cursor = conn.cursor()

    # Build query with optional filters
    where_clauses = []
    params = []

    if filter_label == "unlabeled":
        where_clauses.append("main_triangle_label IS NULL")
    elif filter_label == "labeled":
        where_clauses.append("main_triangle_label IS NOT NULL")
    elif filter_label:
        where_clauses.append("main_triangle_label = ?")
        params.append(filter_label)

    if search:
        where_clauses.append("(signname LIKE ? OR name311 LIKE ? OR gispropnum LIKE ?)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # Get total count
    cursor.execute(f"SELECT COUNT(*) FROM parks{where_sql}", params)
    total = cursor.fetchone()[0]

    # Get parks
    cursor.execute(
        f"""
        SELECT id, source_id, signname, name311, typecategory, subcategory, 
               borough, acres, geometry, main_triangle_label, triangle_note
        FROM parks
        {where_sql}
        ORDER BY id
        LIMIT ? OFFSET ?
    """,
        params + [limit, offset],
    )

    parks = []
    for row in cursor.fetchall():
        parks.append(
            {
                "id": row["id"],
                "source_id": row["source_id"],
                "signname": row["signname"],
                "name311": row["name311"],
                "typecategory": row["typecategory"],
                "subcategory": row["subcategory"],
                "borough": row["borough"],
                "acres": row["acres"],
                "geometry": json.loads(row["geometry"]),
                "main_triangle_label": row["main_triangle_label"],
                "triangle_note": row["triangle_note"],
            }
        )

    conn.close()

    return {"total": total, "offset": offset, "limit": limit, "parks": parks}


@app.get("/api/parks/{park_id}")
def get_park(park_id: int):
    """Get a single park by ID."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, source_id, signname, name311, typecategory, subcategory,
               borough, acres, address, location, geometry, 
               main_triangle_label, triangle_note
        FROM parks WHERE id = ?
    """,
        (park_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Park not found")

    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "signname": row["signname"],
        "name311": row["name311"],
        "typecategory": row["typecategory"],
        "subcategory": row["subcategory"],
        "borough": row["borough"],
        "acres": row["acres"],
        "address": row["address"],
        "location": row["location"],
        "geometry": json.loads(row["geometry"]),
        "main_triangle_label": row["main_triangle_label"],
        "triangle_note": row["triangle_note"],
    }


@app.post("/api/parks/{park_id}/label")
def label_park(park_id: int, label: LabelUpdate):
    """Update the label for a park."""
    conn = get_db()
    cursor = conn.cursor()

    # Validate label value
    valid_labels = [
        "Definitely Triangle",
        "Most Likely a Triangle",
        "Somewhat a Triangle",
        "Not Triangle",
    ]
    if label.main_triangle_label not in valid_labels:
        raise HTTPException(
            status_code=400, detail=f"Invalid label. Must be one of: {valid_labels}"
        )

    cursor.execute(
        """
        UPDATE parks 
        SET main_triangle_label = ?, triangle_note = ?, labeled_at = ?
        WHERE id = ?
    """,
        (
            label.main_triangle_label,
            label.triangle_note,
            datetime.now().isoformat(),
            park_id,
        ),
    )

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Park not found")

    conn.commit()
    conn.close()

    return {"status": "success", "park_id": park_id}


@app.get("/api/stats")
def get_stats():
    """Get labeling statistics."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM parks")
    total = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT main_triangle_label, COUNT(*) as count
        FROM parks
        GROUP BY main_triangle_label
    """
    )

    stats = {"total": total, "labels": {}}
    for row in cursor.fetchall():
        label = row[0] if row[0] else "Unlabeled"
        stats["labels"][label] = row[1]

    conn.close()
    return stats


@app.get("/api/next-unlabeled")
def get_next_unlabeled(after_id: int = Query(0)):
    """Get the next unlabeled park after the given ID."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id FROM parks 
        WHERE main_triangle_label IS NULL AND id > ?
        ORDER BY id LIMIT 1
    """,
        (after_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"next_id": None}

    return {"next_id": row[0]}


@app.get("/api/random-unlabeled")
def get_random_unlabeled():
    """Get a random unlabeled park."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id FROM parks 
        WHERE main_triangle_label IS NULL
    """
    )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {"random_id": None}

    random_row = random.choice(rows)
    return {"random_id": random_row[0]}


@app.get("/api/notes")
def get_existing_notes():
    """Get existing note options from the database for Most Likely and Somewhat labels."""
    conn = get_db()
    cursor = conn.cursor()

    # Get all unique notes grouped by label type
    cursor.execute(
        """
        SELECT main_triangle_label, triangle_note 
        FROM parks 
        WHERE triangle_note IS NOT NULL 
        AND main_triangle_label IN ('Most Likely a Triangle', 'Somewhat a Triangle')
    """
    )

    # Parse and collect unique note fragments
    options = {"Most Likely a Triangle": set(), "Somewhat a Triangle": set()}

    for row in cursor.fetchall():
        label = row[0]
        note = row[1]
        if label in options and note:
            # Notes may be combined with ' | ' or '; ' - split them
            for part in note.replace(" | ", ";").split(";"):
                part = part.strip()
                if part:
                    options[label].add(part)

    conn.close()

    # Convert sets to sorted lists
    result = {label: sorted(list(notes)) for label, notes in options.items()}

    return {"options": result}


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    """Serve the main labeling UI."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Triangle Labeling Tool</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://api.mapbox.com/mapbox-gl-js/v3.0.1/mapbox-gl.js"></script>
    <link href="https://api.mapbox.com/mapbox-gl-js/v3.0.1/mapbox-gl.css" rel="stylesheet" />
    <style>
        body {{ font-family: 'SF Mono', 'Menlo', 'Monaco', monospace; margin: 0; padding: 0; }}
        #map {{ position: fixed; top: 0; left: 0; right: 0; bottom: 0; }}
        .floating-panel {{ 
            position: fixed; 
            z-index: 1000; 
            background: rgba(255,255,255,0.95); 
            border: 2px solid black;
            box-shadow: 4px 4px 0 rgba(0,0,0,0.2);
        }}
        .label-btn {{ transition: all 0.1s ease; }}
        .label-btn:hover {{ transform: translateY(-1px); }}
        .label-btn.selected {{ background: black !important; color: white !important; }}
        .collapse-btn {{ cursor: pointer; user-select: none; }}
        .park-item {{ transition: background 0.1s; }}
        .park-item:hover {{ background: #f0f0f0; }}
        .park-item.active {{ background: #e0e0e0; }}
    </style>
</head>
<body>
    <!-- Full Screen Map -->
    <div id="map"></div>

    <!-- Floating Panel: Stats & Controls -->
    <div class="floating-panel top-4 left-4 max-w-sm">
        <!-- Header with Stats -->
        <div class="p-3 border-b-2 border-black">
            <div class="flex justify-between items-center mb-2">
                <h1 class="font-bold text-lg">Triangle Labels</h1>
                <span class="text-xs text-gray-500">ID: <span id="current-id">-</span></span>
            </div>
            <div class="flex gap-4 text-xs">
                <span>Total: <strong id="stat-total">-</strong></span>
                <span>Done: <strong id="stat-labeled">-</strong></span>
                <span>Left: <strong id="stat-remaining">-</strong></span>
            </div>
        </div>

        <!-- Park Info -->
        <div id="park-info" class="p-3 border-b-2 border-black">
            <p class="text-gray-500 text-sm">Loading...</p>
        </div>

        <!-- Label Buttons -->
        <div class="p-3 border-b-2 border-black">
            <div class="grid grid-cols-2 gap-2">
                <button onclick="setLabel('Definitely Triangle')" class="label-btn px-2 py-2 border-2 border-black text-xs hover:bg-black hover:text-white" data-label="Definitely Triangle">
                    <span class="font-bold">[1]</span> Definitely
                </button>
                <button onclick="setLabel('Most Likely a Triangle')" class="label-btn px-2 py-2 border-2 border-black text-xs hover:bg-black hover:text-white" data-label="Most Likely a Triangle">
                    <span class="font-bold">[2]</span> Most Likely
                </button>
                <button onclick="setLabel('Somewhat a Triangle')" class="label-btn px-2 py-2 border-2 border-black text-xs hover:bg-black hover:text-white" data-label="Somewhat a Triangle">
                    <span class="font-bold">[3]</span> Somewhat
                </button>
                <button onclick="setLabel('Not Triangle')" class="label-btn px-2 py-2 border-2 border-black text-xs hover:bg-black hover:text-white" data-label="Not Triangle">
                    <span class="font-bold">[4]</span> Not Triangle
                </button>
            </div>
            <div class="flex gap-2 mt-2">
                <button onclick="goRandomUnlabeled()" class="flex-1 px-2 py-1.5 border border-black text-xs hover:bg-gray-100">
                    <span class="font-bold">[N]</span> Random Next
                </button>
                <button onclick="goNextUnlabeled()" class="flex-1 px-2 py-1.5 border border-black text-xs hover:bg-gray-100">
                    <span class="font-bold">[→]</span> Next Unlabeled
                </button>
            </div>
        </div>

        <!-- Collapsible Park List -->
        <div class="border-b-2 border-black">
            <div class="collapse-btn p-2 flex justify-between items-center hover:bg-gray-100" onclick="toggleList()">
                <span class="text-xs font-bold">PARK LIST</span>
                <span id="collapse-icon" class="text-xs">▼</span>
            </div>
            <div id="list-container" class="hidden">
                <div class="p-2 border-t border-gray-300">
                    <div class="flex gap-1 mb-2">
                        <input type="text" id="search-input" placeholder="Search..." 
                               class="flex-1 px-2 py-1 border border-black text-xs focus:outline-none">
                        <button onclick="searchParks()" class="px-2 py-1 bg-black text-white text-xs">Go</button>
                    </div>
                    <div class="flex gap-1 flex-wrap text-xs mb-2">
                        <button onclick="filterParks('all')" class="filter-btn px-1.5 py-0.5 border border-black text-xs hover:bg-black hover:text-white" data-filter="all">All</button>
                        <button onclick="filterParks('unlabeled')" class="filter-btn px-1.5 py-0.5 border border-black text-xs hover:bg-black hover:text-white" data-filter="unlabeled">Unlabeled</button>
                        <button onclick="filterParks('labeled')" class="filter-btn px-1.5 py-0.5 border border-black text-xs hover:bg-black hover:text-white" data-filter="labeled">Labeled</button>
                    </div>
                </div>
                <div id="park-list" class="max-h-48 overflow-y-auto border-t border-gray-300">
                    <!-- Parks loaded here -->
                </div>
                <div class="p-2 border-t border-gray-300 flex justify-between items-center text-xs">
                    <button onclick="prevPage()" id="prev-btn" class="px-2 py-1 border border-black hover:bg-black hover:text-white disabled:opacity-30">←</button>
                    <span id="page-info" class="text-gray-500">-</span>
                    <button onclick="nextPage()" id="next-btn" class="px-2 py-1 border border-black hover:bg-black hover:text-white disabled:opacity-30">→</button>
                </div>
            </div>
        </div>

        <!-- Keyboard Hints -->
        <div class="p-2 text-xs text-gray-500">
            <span class="font-bold">Keys:</span> 1-4 label, N random, → next, L toggle list
        </div>
    </div>

    <!-- Current Label Indicator (bottom right) -->
    <div id="label-indicator" class="floating-panel bottom-4 right-4 p-3 hidden">
        <div class="text-xs text-gray-500 mb-1">Current Label</div>
        <div id="label-display" class="font-bold text-lg">-</div>
    </div>

    <script>
        // Config
        const MAPBOX_TOKEN = '{MAPBOX_ACCESS_TOKEN}';
        mapboxgl.accessToken = MAPBOX_TOKEN;

        // State
        let currentPark = null;
        let selectedLabel = null;
        let parks = [];
        let offset = 0;
        let limit = 30;
        let total = 0;
        let currentFilter = 'unlabeled';
        let searchQuery = '';
        let map = null;
        let listExpanded = false;

        // Initialize map
        function initMap() {{
            map = new mapboxgl.Map({{
                container: 'map',
                style: 'mapbox://styles/mapbox/light-v11',
                center: [-73.95, 40.73],
                zoom: 10
            }});

            map.on('load', () => {{
                // Add source for park polygon
                map.addSource('park-polygon', {{
                    type: 'geojson',
                    data: {{ type: 'FeatureCollection', features: [] }}
                }});

                // Add fill layer
                map.addLayer({{
                    id: 'park-fill',
                    type: 'fill',
                    source: 'park-polygon',
                    paint: {{
                        'fill-color': '#ff0000',
                        'fill-opacity': 0.35
                    }}
                }});

                // Add outline layer
                map.addLayer({{
                    id: 'park-outline',
                    type: 'line',
                    source: 'park-polygon',
                    paint: {{
                        'line-color': '#cc0000',
                        'line-width': 3
                    }}
                }});

                // Load first random unlabeled park
                goRandomUnlabeled();
            }});
        }}

        // Toggle list visibility
        function toggleList() {{
            listExpanded = !listExpanded;
            document.getElementById('list-container').classList.toggle('hidden', !listExpanded);
            document.getElementById('collapse-icon').textContent = listExpanded ? '▲' : '▼';
            if (listExpanded && parks.length === 0) {{
                loadParks();
            }}
        }}

        // Load parks
        async function loadParks() {{
            const filterParam = currentFilter === 'all' ? '' : `&filter_label=${{encodeURIComponent(currentFilter)}}`;
            const searchParam = searchQuery ? `&search=${{encodeURIComponent(searchQuery)}}` : '';
            const response = await fetch(`/api/parks?offset=${{offset}}&limit=${{limit}}${{filterParam}}${{searchParam}}`);
            const data = await response.json();
            parks = data.parks;
            total = data.total;
            renderParkList();
            updatePageInfo();
        }}

        // Render park list
        function renderParkList() {{
            const list = document.getElementById('park-list');
            if (parks.length === 0) {{
                list.innerHTML = '<p class="p-2 text-gray-500 text-xs">No parks found</p>';
                return;
            }}
            list.innerHTML = parks.map(park => `
                <div class="park-item p-2 border-b border-gray-200 cursor-pointer text-xs ${{currentPark?.id === park.id ? 'active' : ''}}"
                     onclick="selectPark(${{park.id}})">
                    <div class="flex justify-between items-start">
                        <div class="truncate flex-1 mr-2">
                            <span class="font-medium">${{park.signname || park.name311 || 'Unnamed'}}</span>
                        </div>
                        <span class="px-1 py-0.5 ${{getLabelClass(park.main_triangle_label)}} whitespace-nowrap">
                            ${{getLabelShort(park.main_triangle_label)}}
                        </span>
                    </div>
                </div>
            `).join('');
        }}

        // Get label display class
        function getLabelClass(label) {{
            if (!label) return 'bg-gray-200 text-gray-600';
            if (label === 'Definitely Triangle') return 'bg-black text-white';
            if (label === 'Most Likely a Triangle') return 'bg-gray-700 text-white';
            if (label === 'Somewhat a Triangle') return 'bg-gray-400 text-white';
            return 'bg-white border border-black';
        }}

        // Get short label
        function getLabelShort(label) {{
            if (!label) return '?';
            if (label === 'Definitely Triangle') return '✓';
            if (label === 'Most Likely a Triangle') return '◐';
            if (label === 'Somewhat a Triangle') return '○';
            return '✗';
        }}

        // Select park
        async function selectPark(parkId) {{
            const response = await fetch(`/api/parks/${{parkId}}`);
            currentPark = await response.json();
            selectedLabel = currentPark.main_triangle_label;
            renderParkInfo();
            renderParkOnMap();
            updateLabelButtons();
            updateLabelIndicator();
            document.getElementById('current-id').textContent = currentPark.id;
            if (listExpanded) renderParkList();
        }}

        // Render park info
        function renderParkInfo() {{
            const info = document.getElementById('park-info');
            info.innerHTML = `
                <h2 class="font-bold text-sm mb-1 truncate">${{currentPark.signname || currentPark.name311 || 'Unnamed Park'}}</h2>
                <div class="text-xs text-gray-600">
                    <span>${{currentPark.typecategory}}</span> · 
                    <span>${{currentPark.borough}}</span> · 
                    <span>${{currentPark.acres}} ac</span>
                </div>
                ${{currentPark.main_triangle_label ? `
                    <div class="mt-2 px-2 py-1 bg-gray-100 text-xs">
                        <strong>Label:</strong> ${{currentPark.main_triangle_label}}
                        ${{currentPark.triangle_note ? `<br><span class="text-gray-500">Note: ${{currentPark.triangle_note}}</span>` : ''}}
                    </div>
                ` : ''}}
            `;
        }}

        // Render park on map (instant, no animation)
        function renderParkOnMap() {{
            if (!map || !currentPark?.geometry) return;

            const geojson = {{
                type: 'Feature',
                geometry: currentPark.geometry,
                properties: {{}}
            }};

            map.getSource('park-polygon').setData({{
                type: 'FeatureCollection',
                features: [geojson]
            }});

            // Calculate bounding box and zoom to it INSTANTLY
            const coords = [];
            const extractCoords = (arr) => {{
                if (typeof arr[0] === 'number') {{
                    coords.push(arr);
                }} else {{
                    arr.forEach(extractCoords);
                }}
            }};
            extractCoords(currentPark.geometry.coordinates);

            if (coords.length > 0) {{
                const bounds = coords.reduce((bounds, coord) => {{
                    return bounds.extend(coord);
                }}, new mapboxgl.LngLatBounds(coords[0], coords[0]));

                // Use jumpTo for instant transition (no animation)
                const center = bounds.getCenter();
                map.jumpTo({{
                    center: center,
                    zoom: 17
                }});
                
                // Then fit bounds instantly
                map.fitBounds(bounds, {{ 
                    padding: 100, 
                    maxZoom: 18,
                    duration: 0  // instant
                }});
            }}
        }}

        // Update label button states
        function updateLabelButtons() {{
            document.querySelectorAll('.label-btn').forEach(btn => {{
                const label = btn.dataset.label;
                if (label === selectedLabel) {{
                    btn.classList.add('selected');
                }} else {{
                    btn.classList.remove('selected');
                }}
            }});
        }}

        // Update label indicator
        function updateLabelIndicator() {{
            const indicator = document.getElementById('label-indicator');
            const display = document.getElementById('label-display');
            if (selectedLabel) {{
                indicator.classList.remove('hidden');
                display.textContent = selectedLabel;
            }} else {{
                indicator.classList.add('hidden');
            }}
        }}

        // Set label and auto-save
        async function setLabel(label) {{
            if (!currentPark) return;
            
            selectedLabel = label;
            updateLabelButtons();
            updateLabelIndicator();
            
            // For Most Likely or Somewhat, open notes page
            if (label === 'Most Likely a Triangle' || label === 'Somewhat a Triangle') {{
                window.open(`/notes?park_id=${{currentPark.id}}&label=${{encodeURIComponent(label)}}`, '_blank', 'width=500,height=400');
                return;
            }}

            // Auto-save for Definitely and Not Triangle
            await saveLabel();
            goRandomUnlabeled();
        }}

        // Save label
        async function saveLabel(note = null) {{
            if (!currentPark || !selectedLabel) return;

            const response = await fetch(`/api/parks/${{currentPark.id}}/label`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{
                    park_id: currentPark.id,
                    main_triangle_label: selectedLabel,
                    triangle_note: note
                }})
            }});

            if (response.ok) {{
                currentPark.main_triangle_label = selectedLabel;
                currentPark.triangle_note = note;
                loadStats();
                if (listExpanded) loadParks();
                renderParkInfo();
            }}
        }}

        // Go to next unlabeled
        async function goNextUnlabeled() {{
            const afterId = currentPark ? currentPark.id : 0;
            const response = await fetch(`/api/next-unlabeled?after_id=${{afterId}}`);
            const data = await response.json();
            if (data.next_id) {{
                selectPark(data.next_id);
            }} else {{
                alert('No more unlabeled parks!');
            }}
        }}

        // Go to random unlabeled
        async function goRandomUnlabeled() {{
            const response = await fetch('/api/random-unlabeled');
            const data = await response.json();
            if (data.random_id) {{
                selectPark(data.random_id);
            }} else {{
                alert('No more unlabeled parks!');
            }}
        }}

        // Load stats
        async function loadStats() {{
            const response = await fetch('/api/stats');
            const stats = await response.json();
            document.getElementById('stat-total').textContent = stats.total;
            const labeled = stats.total - (stats.labels['Unlabeled'] || 0);
            document.getElementById('stat-labeled').textContent = labeled;
            document.getElementById('stat-remaining').textContent = stats.labels['Unlabeled'] || 0;
        }}

        // Filter parks
        function filterParks(filter) {{
            currentFilter = filter;
            offset = 0;
            loadParks();
            
            document.querySelectorAll('.filter-btn').forEach(btn => {{
                if (btn.dataset.filter === filter) {{
                    btn.classList.add('bg-black', 'text-white');
                }} else {{
                    btn.classList.remove('bg-black', 'text-white');
                }}
            }});
        }}

        // Search parks
        function searchParks() {{
            searchQuery = document.getElementById('search-input').value;
            offset = 0;
            loadParks();
        }}

        // Pagination
        function updatePageInfo() {{
            const start = total > 0 ? offset + 1 : 0;
            const end = Math.min(offset + limit, total);
            document.getElementById('page-info').textContent = `${{start}}-${{end}} / ${{total}}`;
            document.getElementById('prev-btn').disabled = offset === 0;
            document.getElementById('next-btn').disabled = offset + limit >= total;
        }}

        function prevPage() {{
            if (offset > 0) {{
                offset = Math.max(0, offset - limit);
                loadParks();
            }}
        }}

        function nextPage() {{
            if (offset + limit < total) {{
                offset += limit;
                loadParks();
            }}
        }}

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {{
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            
            if (e.key === '1') setLabel('Definitely Triangle');
            if (e.key === '2') setLabel('Most Likely a Triangle');
            if (e.key === '3') setLabel('Somewhat a Triangle');
            if (e.key === '4') setLabel('Not Triangle');
            if (e.key === 'n' || e.key === 'N') goRandomUnlabeled();
            if (e.key === 'ArrowRight') goNextUnlabeled();
            if (e.key === 'l' || e.key === 'L') toggleList();
        }});

        // Search on Enter
        document.getElementById('search-input')?.addEventListener('keydown', (e) => {{
            if (e.key === 'Enter') searchParks();
        }});

        // Listen for messages from notes popup
        window.addEventListener('message', (e) => {{
            if (e.data?.type === 'noteSaved') {{
                // Refresh stats and go to next
                loadStats();
                if (listExpanded) loadParks();
                goRandomUnlabeled();
            }}
        }});

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {{
            initMap();
            loadStats();
        }});
    </script>
</body>
</html>
"""
    return html


@app.get("/notes", response_class=HTMLResponse)
def serve_notes_ui():
    """Serve the notes input UI for Most Likely and Somewhat labels."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Add Note</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ font-family: 'SF Mono', 'Menlo', 'Monaco', monospace; }}
        .option-item {{ transition: all 0.1s; cursor: pointer; }}
        .option-item:hover {{ background: #f0f0f0; }}
        .option-item.checked {{ background: black; color: white; }}
    </style>
</head>
<body class="bg-white p-4">
    <h1 class="font-bold text-lg mb-1">Select Reasons</h1>
    <p class="text-xs text-gray-500 mb-4">
        Park ID: <span id="park-id">-</span> | 
        Label: <span id="label-type">-</span>
    </p>

    <!-- Option Checkboxes -->
    <div class="mb-4">
        <p class="text-xs font-bold mb-2">Select all that apply:</p>
        <div id="options-list" class="border-2 border-black">
            <p class="p-2 text-xs text-gray-500">Loading...</p>
        </div>
    </div>

    <!-- Custom Note -->
    <div class="mb-4">
        <p class="text-xs font-bold mb-2">Additional note (optional):</p>
        <input type="text" id="custom-note" 
               class="w-full px-3 py-2 border-2 border-black text-sm focus:outline-none" 
               placeholder="Type additional note...">
    </div>

    <!-- Buttons -->
    <div class="flex gap-2">
        <button onclick="saveAndClose()" class="flex-1 px-4 py-2 bg-black text-white text-sm hover:bg-gray-800">
            Save & Next [Enter]
        </button>
        <button onclick="skipAndClose()" class="px-4 py-2 border border-black text-sm hover:bg-gray-100">
            Skip [Esc]
        </button>
    </div>

    <script>
        // Get URL params
        const params = new URLSearchParams(window.location.search);
        const parkId = params.get('park_id');
        const label = params.get('label');
        let selectedOptions = new Set();

        document.getElementById('park-id').textContent = parkId;
        document.getElementById('label-type').textContent = label;

        // Load options
        async function loadOptions() {{
            const response = await fetch('/api/notes');
            const data = await response.json();
            const container = document.getElementById('options-list');
            
            const options = data.options[label] || [];
            if (options.length === 0) {{
                container.innerHTML = '<p class="p-2 text-xs text-gray-500">No options available</p>';
                return;
            }}
            
            container.innerHTML = options.map((opt, idx) => `
                <div class="option-item p-2 text-xs border-b border-gray-300 flex items-center gap-2" 
                     onclick="toggleOption(this, '${{opt.replace(/'/g, "\\'")}}')">
                    <span class="w-4 h-4 border border-current flex items-center justify-center text-xs" id="check-${{idx}}"></span>
                    <span>${{opt}}</span>
                </div>
            `).join('');
        }}

        // Toggle option selection
        function toggleOption(el, option) {{
            if (selectedOptions.has(option)) {{
                selectedOptions.delete(option);
                el.classList.remove('checked');
                el.querySelector('span').textContent = '';
            }} else {{
                selectedOptions.add(option);
                el.classList.add('checked');
                el.querySelector('span').textContent = '✓';
            }}
        }}

        // Get combined note
        function getNote() {{
            const parts = [];
            if (selectedOptions.size > 0) {{
                parts.push([...selectedOptions].join('; '));
            }}
            const custom = document.getElementById('custom-note').value.trim();
            if (custom) {{
                parts.push(custom);
            }}
            return parts.length > 0 ? parts.join(' | ') : null;
        }}

        // Save and close
        async function saveAndClose() {{
            const note = getNote();
            await saveLabel(note);
        }}

        // Skip (save without note)
        async function skipAndClose() {{
            await saveLabel(null);
        }}

        // Save label
        async function saveLabel(note) {{
            const response = await fetch(`/api/parks/${{parkId}}/label`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{
                    park_id: parseInt(parkId),
                    main_triangle_label: label,
                    triangle_note: note
                }})
            }});

            if (response.ok) {{
                // Notify parent window to refresh and close this window
                if (window.opener) {{
                    window.opener.postMessage({{ type: 'noteSaved', parkId: parkId }}, '*');
                }}
                window.close();
            }} else {{
                alert('Error saving label');
            }}
        }}

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Enter' && e.target.tagName !== 'INPUT') {{
                saveAndClose();
            }}
            if (e.key === 'Escape') {{
                skipAndClose();
            }}
        }});

        // Enter in input saves
        document.getElementById('custom-note').addEventListener('keydown', (e) => {{
            if (e.key === 'Enter') {{
                saveAndClose();
            }}
        }});

        // Init
        loadOptions();
    </script>
</body>
</html>
"""
    return html


if __name__ == "__main__":
    import uvicorn

    print("Starting Triangle Labeling Tool...")
    print(f"Database: {{DB_PATH}}")
    print(f"Mapbox Token: {{'Set' if MAPBOX_ACCESS_TOKEN else 'NOT SET'}}")
    print("\\nOpen http://localhost:8000 in your browser")
    uvicorn.run(app, host="0.0.0.0", port=8001)
