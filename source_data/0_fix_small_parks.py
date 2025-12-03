#!/usr/bin/env python3
"""
Fix Small Parks - Replace poorly defined polygons with OSM data.

This script identifies specific small parks with poorly defined polygons
and replaces their geometry with more accurate data from OpenStreetMap
via the Overpass API.
"""

import json
import time
from pathlib import Path

import geopandas as gpd
import pyproj
import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import transform
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import textdistance
import logging

# Set up logging for tenacity retry messages
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

console = Console()

# Source and output files
SOURCE_DATA_FILE = Path(__file__).parent / "Parks_Properties_20251119_modified.geojson"
OUTPUT_FILE = Path(__file__).parent / "small_parks_modified.geojson"
ERROR_DIR = Path(__file__).parent / "error"

# Parks to fix - list of :id values from README.md
PARKS_TO_FIX = [
    "row-rbs7.wef6.wevd",  # Sgt. Joyce Kilmer Square
    "row-9kkg.gehr~dasq",  # Luke J. Lang Square
    "row-mnek_ivw9_7zuh",  # Middleburgh Triangle
    "row-8ttk-59ga.xbt7",  # Dwyer Square
    "row-4zsg-7ji2.pm6w",  # Dunningham Triangle
    "row-jd95_dw66-vbrq",  # Corporal Frank F. Fagan Sq.
    "row-8ni5.z4dn.nij8",  # Freedom Triangle
    "row-2km6.y89y~pv89",  # Fowler Square
    "row-mp7m-uyq3.tvje",  # Catholic War Veterans Square
    "row-2hxt-3ruf-b3wk",  # O'Sullivan Plaza
    "row-yx4a~97r8.a7xt",  # Alben Square
    "row-nzjh~3md4-m5su",  # Metro Triangle
    "row-apz9_cx2f_g9fu",  # Myrtle Ave., Cypress Ave., Putnam Ave.
    "row-gika_59qa~36pe",  # Grant Gore
    "row-vd76-qn8k_asmy",  # Woodrow Wilson Triangle
    "row-5ptx.dtp6-spm9",  # Horsebrook Island
    "row-tewt.g6s5.hszk",  # Jacob Riis Triangle
    "row-nebb~ym7k-iyx3",  # Fleetwood Triangle
    "row-g9bt-xgu8-t2i8",  # Ascenzi Square
    "row-ugix_fjq9-jf6g",  # TODO: ADD TO DOCS
    "row-teye-5c89-najb",
    "row-vg2j.x4qa~ptrw",
    "row-cyyp-hhy5_29nw",
    "row-u7te.txxg~gmk3",
]

# Bounding box expansion in meters
BBOX_EXPANSION_M = 200

# Overpass API endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Coordinate transformers
WGS84_TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
UTM_TO_WGS84 = pyproj.Transformer.from_crs("EPSG:32618", "EPSG:4326", always_xy=True)


def expand_bbox(bounds: tuple, expansion_m: float) -> tuple:
    """
    Expand a bounding box by a fixed distance in meters.

    Args:
        bounds: (minx, miny, maxx, maxy) in WGS84
        expansion_m: Expansion distance in meters

    Returns:
        Expanded bounding box in WGS84
    """
    minx, miny, maxx, maxy = bounds

    # Convert corners to UTM
    minx_utm, miny_utm = WGS84_TO_UTM.transform(minx, miny)
    maxx_utm, maxy_utm = WGS84_TO_UTM.transform(maxx, maxy)

    # Expand in UTM coordinates
    minx_utm -= expansion_m
    miny_utm -= expansion_m
    maxx_utm += expansion_m
    maxy_utm += expansion_m

    # Convert back to WGS84
    minx_wgs, miny_wgs = UTM_TO_WGS84.transform(minx_utm, miny_utm)
    maxx_wgs, maxy_wgs = UTM_TO_WGS84.transform(maxx_utm, maxy_utm)

    return (minx_wgs, miny_wgs, maxx_wgs, maxy_wgs)


@retry(
    retry=retry_if_exception_type(
        (requests.exceptions.RequestException, requests.exceptions.Timeout)
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def query_overpass(south: float, west: float, north: float, east: float) -> dict:
    """
    Query Overpass API for parks within a bounding box.

    Args:
        south, west, north, east: Bounding box coordinates

    Returns:
        Raw Overpass API response as dict

    Raises:
        requests.exceptions.RequestException: If all retries fail
    """
    # Query for various park-like features including plazas, pedestrian areas, etc.
    query = f"""
[out:json][timeout:60];
(
  // Parks and gardens
  way["leisure"="park"]({south},{west},{north},{east});
  relation["leisure"="park"]({south},{west},{north},{east});
  way["leisure"="garden"]({south},{west},{north},{east});
  relation["leisure"="garden"]({south},{west},{north},{east});
  way["leisure"="playground"]({south},{west},{north},{east});
  relation["leisure"="playground"]({south},{west},{north},{east});
  
  // Recreation areas
  way["landuse"="recreation_ground"]({south},{west},{north},{east});
  relation["landuse"="recreation_ground"]({south},{west},{north},{east});
  way["landuse"="grass"]({south},{west},{north},{east});
  relation["landuse"="grass"]({south},{west},{north},{east});
  
  // Plazas and pedestrian areas (common for small triangular parks)
  way["highway"="pedestrian"]["area"="yes"]({south},{west},{north},{east});
  relation["highway"="pedestrian"]["area"="yes"]({south},{west},{north},{east});
  way["place"="square"]({south},{west},{north},{east});
  relation["place"="square"]({south},{west},{north},{east});
  way["leisure"="pitch"]({south},{west},{north},{east});
  relation["leisure"="pitch"]({south},{west},{north},{east});
);
out body;
>;
out skel qt;
"""
    response = requests.get(OVERPASS_URL, params={"data": query}, timeout=120)
    response.raise_for_status()
    return response.json()


def parse_overpass_response(data: dict) -> list[dict]:
    """
    Parse Overpass API response into GeoJSON features.

    Args:
        data: Raw Overpass API response

    Returns:
        List of GeoJSON feature dicts
    """
    nodes = {}
    ways = {}
    relations = {}

    for element in data["elements"]:
        if element["type"] == "node":
            nodes[element["id"]] = (element["lon"], element["lat"])
        elif element["type"] == "way":
            ways[element["id"]] = element
        elif element["type"] == "relation":
            relations[element["id"]] = element

    def way_to_coordinates(way):
        coords = []
        for node_id in way.get("nodes", []):
            if node_id in nodes:
                coords.append(nodes[node_id])
        return coords

    def build_polygon_from_way(way):
        coords = way_to_coordinates(way)
        if len(coords) < 3:
            return None
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return {"type": "Polygon", "coordinates": [coords]}

    def build_multipolygon_from_relation(relation):
        outer_rings = []
        inner_rings = []

        for member in relation.get("members", []):
            if member["type"] == "way" and member["ref"] in ways:
                way = ways[member["ref"]]
                coords = way_to_coordinates(way)
                if len(coords) >= 3:
                    if coords[0] != coords[-1]:
                        coords.append(coords[0])
                    role = member.get("role", "outer")
                    if role == "inner":
                        inner_rings.append(coords)
                    else:
                        outer_rings.append(coords)

        if not outer_rings:
            return None

        if len(outer_rings) == 1:
            rings = [outer_rings[0]] + inner_rings
            return {"type": "Polygon", "coordinates": rings}

        polygons = [[ring] for ring in outer_rings]
        return {"type": "MultiPolygon", "coordinates": polygons}

    def is_park_like_feature(tags: dict) -> bool:
        """Check if tags indicate a park-like feature."""
        # Leisure features
        if tags.get("leisure") in ["park", "playground", "garden", "pitch"]:
            return True
        # Landuse features
        if tags.get("landuse") in ["recreation_ground", "grass"]:
            return True
        # Pedestrian areas (plazas, squares)
        if tags.get("highway") == "pedestrian" and tags.get("area") == "yes":
            return True
        # Named squares/plazas
        if tags.get("place") == "square":
            return True
        return False

    features = []

    # Process ways
    for way_id, way in ways.items():
        tags = way.get("tags", {})
        if is_park_like_feature(tags):
            geometry = build_polygon_from_way(way)
            if geometry:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": {
                            "osm_id": way_id,
                            "osm_type": "way",
                            "name": tags.get("name", ""),
                            **{k: v for k, v in tags.items()},
                        },
                    }
                )

    # Process relations
    for rel_id, relation in relations.items():
        tags = relation.get("tags", {})
        if is_park_like_feature(tags):
            geometry = build_multipolygon_from_relation(relation)
            if geometry:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": {
                            "osm_id": rel_id,
                            "osm_type": "relation",
                            "name": tags.get("name", ""),
                            **{k: v for k, v in tags.items()},
                        },
                    }
                )

    return features


def calculate_overlap(geom1, geom2) -> float:
    """
    Calculate the overlap ratio between two geometries.

    Returns the intersection area divided by the union area (IoU).
    """
    try:
        if not geom1.is_valid:
            geom1 = geom1.buffer(0)
        if not geom2.is_valid:
            geom2 = geom2.buffer(0)

        intersection = geom1.intersection(geom2)
        union = geom1.union(geom2)

        if union.area == 0:
            return 0

        return intersection.area / union.area
    except Exception:
        return 0


def find_best_match(
    original_geom, osm_features: list[dict], park_name: str
) -> tuple[dict | None, float]:
    """
    Find the OSM feature with the best overlap with the original geometry.

    Args:
        original_geom: Original park geometry
        osm_features: List of OSM feature dicts
        park_name: Name of the park for logging

    Returns:
        Tuple of (best matching feature, overlap score)
    """
    best_match = None
    best_overlap = 0

    # Project original geometry to UTM for accurate area comparison
    original_proj = transform(WGS84_TO_UTM.transform, original_geom)

    for feature in osm_features:
        try:
            osm_geom = shape(feature["geometry"])
            osm_proj = transform(WGS84_TO_UTM.transform, osm_geom)

            overlap = calculate_overlap(original_proj, osm_proj)

            if overlap > best_overlap:
                best_overlap = overlap
                best_match = feature

        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not process OSM feature: {e}[/yellow]"
            )
            continue

    return best_match, best_overlap


def find_best_name_match(
    park_name: str, osm_features: list[dict], min_similarity: float = 0.6
) -> tuple[dict | None, float]:
    """
    Find the OSM feature with the most similar name using Levenshtein distance.

    Args:
        park_name: Original park name to match
        osm_features: List of OSM feature dicts
        min_similarity: Minimum similarity threshold (0-1) to accept a match

    Returns:
        Tuple of (best matching feature, similarity score)
    """
    best_match = None
    best_similarity = 0

    # Normalize park name for comparison
    park_name_normalized = park_name.lower().strip()

    for feature in osm_features:
        osm_name = feature["properties"].get("name", "")
        if not osm_name:
            continue

        # Normalize OSM name
        osm_name_normalized = osm_name.lower().strip()

        # Calculate normalized Levenshtein similarity (0-1, higher is better)
        similarity = textdistance.levenshtein.normalized_similarity(
            park_name_normalized, osm_name_normalized
        )

        if similarity > best_similarity:
            best_similarity = similarity
            best_match = feature

    # Only return match if above threshold
    if best_similarity >= min_similarity:
        return best_match, best_similarity

    return None, best_similarity


def fix_park(park_row, gdf: gpd.GeoDataFrame) -> dict:
    """
    Fix a single park's geometry using OSM data.

    Args:
        park_row: Row from the GeoDataFrame
        gdf: Full GeoDataFrame for context

    Returns:
        Dict with keys: success, message, new_geom, and debug info for errors
    """
    park_id = park_row[":id"]
    park_name = park_row.get("name311", park_row.get("signname", "Unknown"))
    original_geom = park_row.geometry

    # Get and expand bounding box
    bounds = original_geom.bounds
    expanded_bounds = expand_bbox(bounds, BBOX_EXPANSION_M)
    west, south, east, north = expanded_bounds

    # Build result dict with debug info
    result = {
        "success": False,
        "message": "",
        "new_geom": None,
        "park_id": park_id,
        "park_name": park_name,
        "original_bounds": bounds,
        "expanded_bounds": expanded_bounds,
        "query_bbox": {"south": south, "west": west, "north": north, "east": east},
        "raw_response": None,
        "osm_features": None,
        "best_match": None,
        "best_overlap": None,
        "name_match": None,
        "name_similarity": None,
        "match_method": None,
    }

    # Query Overpass
    try:
        data = query_overpass(south, west, north, east)
        result["raw_response"] = data
    except Exception as e:
        result["message"] = f"Overpass query failed: {e}"
        return result

    # Parse response
    osm_features = parse_overpass_response(data)
    result["osm_features"] = osm_features

    if not osm_features:
        result["message"] = "No OSM features found in area"
        return result

    # Find best match
    best_match, overlap = find_best_match(original_geom, osm_features, park_name)
    result["best_match"] = best_match
    result["best_overlap"] = overlap

    if best_match is None:
        result["message"] = "No matching OSM feature found"
        return result

    # Check if overlap is sufficient
    if overlap >= 0.01:  # 1% or more overlap - use geometry match
        result["match_method"] = "geometry"
        final_match = best_match
        osm_name = final_match["properties"].get("name", "unnamed")
        result["success"] = True
        result["message"] = f"Matched with OSM '{osm_name}' (overlap: {overlap:.1%})"
    else:
        # Low overlap - try name matching as fallback
        name_match, name_similarity = find_best_name_match(park_name, osm_features)
        result["name_match"] = name_match
        result["name_similarity"] = name_similarity

        if name_match is not None:
            result["match_method"] = "name"
            final_match = name_match
            osm_name = final_match["properties"].get("name", "unnamed")
            result["success"] = True
            result["message"] = (
                f"Matched by name '{osm_name}' (similarity: {name_similarity:.1%}, "
                f"geo overlap: {overlap:.1%})"
            )
        else:
            result["message"] = (
                f"No match: overlap too low ({overlap:.1%}) and "
                f"best name similarity {name_similarity:.1%} below threshold"
            )
            return result

    # Convert to MultiPolygon if needed (to match source data format)
    new_geom = shape(final_match["geometry"])
    if isinstance(new_geom, Polygon):
        new_geom = MultiPolygon([new_geom])

    result["new_geom"] = new_geom
    return result


def save_error_log(result: dict, error_dir: Path) -> None:
    """
    Save detailed error log for a failed park fix attempt.

    Args:
        result: Result dict from fix_park
        error_dir: Directory to save error logs
    """
    # Create error directory if needed
    error_dir.mkdir(parents=True, exist_ok=True)

    # Create a safe filename from park name
    park_name = result["park_name"]
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in park_name)
    safe_name = safe_name.replace(" ", "_")[:50]

    filename = error_dir / f"{safe_name}.json"

    # Prepare serializable error log
    error_log = {
        "park_id": result["park_id"],
        "park_name": result["park_name"],
        "error_message": result["message"],
        "original_bounds": result["original_bounds"],
        "expanded_bounds": result["expanded_bounds"],
        "query_bbox": result["query_bbox"],
        "raw_response_element_count": (
            len(result["raw_response"].get("elements", []))
            if result["raw_response"]
            else 0
        ),
        "raw_response": result["raw_response"],
        "osm_features_count": (
            len(result["osm_features"]) if result["osm_features"] else 0
        ),
        "osm_features": result["osm_features"],
        "best_match": result["best_match"],
        "best_overlap": result["best_overlap"],
        "name_match": result.get("name_match"),
        "name_similarity": result.get("name_similarity"),
        "match_method": result.get("match_method"),
    }

    with open(filename, "w") as f:
        json.dump(error_log, f, indent=2)

    console.print(f"  [dim]Saved error log: {filename.name}[/dim]")


def main():
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════[/bold cyan]"
    )
    console.print(
        "[bold cyan]        Fix Small Parks - OSM Data Replacement         [/bold cyan]"
    )
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════[/bold cyan]\n"
    )

    # Load source data
    console.print(f"[cyan]Loading source data from:[/cyan] {SOURCE_DATA_FILE}")
    gdf = gpd.read_file(SOURCE_DATA_FILE)
    console.print(f"[green]Loaded {len(gdf)} parks[/green]\n")

    # Load existing modifications if available
    existing_modified = {}
    already_processed_ids = set()
    if OUTPUT_FILE.exists():
        console.print(
            f"[cyan]Loading existing modifications from:[/cyan] {OUTPUT_FILE}"
        )
        existing_gdf = gpd.read_file(OUTPUT_FILE)
        for _, row in existing_gdf.iterrows():
            park_id = row[":id"]
            existing_modified[park_id] = row.to_dict()
            already_processed_ids.add(park_id)
        console.print(
            f"[green]Found {len(already_processed_ids)} already processed parks[/green]\n"
        )

    # Filter to parks we want to fix
    parks_to_fix = gdf[gdf[":id"].isin(PARKS_TO_FIX)].copy()
    console.print(
        f"[cyan]Found {len(parks_to_fix)} parks to fix out of {len(PARKS_TO_FIX)} specified[/cyan]"
    )

    # Filter out already processed parks
    parks_to_process = parks_to_fix[~parks_to_fix[":id"].isin(already_processed_ids)]
    if len(already_processed_ids) > 0:
        console.print(
            f"[dim]Skipping {len(already_processed_ids)} already processed parks[/dim]"
        )
    console.print(f"[cyan]Will process {len(parks_to_process)} new parks[/cyan]\n")

    if len(parks_to_fix) < len(PARKS_TO_FIX):
        missing = set(PARKS_TO_FIX) - set(parks_to_fix[":id"])
        console.print(f"[yellow]Missing parks: {missing}[/yellow]\n")

    # Results tracking
    results = []
    modified_parks = list(existing_modified.values())  # Start with existing

    # Add results for already processed parks
    for park_id in already_processed_ids:
        park_data = existing_modified[park_id]
        results.append(
            {
                "park_id": park_id,
                "park_name": park_data.get(
                    "name311", park_data.get("signname", "Unknown")
                ),
                "success": True,
                "message": "(already processed)",
            }
        )

    # Process each new park
    if len(parks_to_process) > 0:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for idx, (_, park_row) in enumerate(parks_to_process.iterrows()):
                park_id = park_row[":id"]
                park_name = park_row.get("name311", park_row.get("signname", "Unknown"))

                task = progress.add_task(f"Processing: {park_name[:40]}...", total=None)

                result = fix_park(park_row, gdf)

                if result["success"] and result["new_geom"] is not None:
                    # Create modified park record
                    modified_park = park_row.to_dict()
                    modified_park["geometry"] = result["new_geom"]
                    modified_park["osm_fixed"] = True
                    modified_park["osm_fix_message"] = result["message"]
                    modified_parks.append(modified_park)
                else:
                    # Save error log for failed parks
                    save_error_log(result, ERROR_DIR)

                results.append(
                    {
                        "park_id": park_id,
                        "park_name": park_name,
                        "success": result["success"],
                        "message": result["message"],
                    }
                )

                progress.remove_task(task)

                # Rate limiting - be nice to Overpass API
                if idx < len(parks_to_process) - 1:
                    time.sleep(4)

    # Print results table
    console.print(
        "\n[bold cyan]═══════════════════════════════════════════════════════[/bold cyan]"
    )
    console.print(
        "[bold cyan]                       Results                          [/bold cyan]"
    )
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════[/bold cyan]\n"
    )

    table = Table(title="Park Fix Results")
    table.add_column("Park Name", style="cyan", max_width=35)
    table.add_column("Status", style="bold")
    table.add_column("Message", max_width=40)

    for result in results:
        if result["message"] == "(already processed)":
            status = "[dim]● Cached[/dim]"
        elif result["success"]:
            status = "[green]✓ Fixed[/green]"
        else:
            status = "[red]✗ Failed[/red]"
        table.add_row(result["park_name"][:35], status, result["message"][:40])

    console.print(table)

    # Summary
    successful = sum(1 for r in results if r["success"])
    cached = sum(1 for r in results if r["message"] == "(already processed)")
    newly_fixed = successful - cached
    console.print(
        f"\n[bold]Summary:[/bold] {successful}/{len(results)} parks fixed "
        f"({newly_fixed} new, {cached} cached)"
    )

    # Save output
    if modified_parks:
        # Create GeoDataFrame with modified parks
        modified_gdf = gpd.GeoDataFrame(modified_parks, crs="EPSG:4326")
        modified_gdf.to_file(OUTPUT_FILE, driver="GeoJSON")
        console.print(
            f"\n[bold green]Saved {len(modified_parks)} modified parks to:[/bold green] {OUTPUT_FILE}"
        )
    else:
        console.print(
            "\n[yellow]No parks were modified. Output file not created.[/yellow]"
        )


if __name__ == "__main__":
    main()
