#!/usr/bin/env python3
"""
Download satellite images for NYC parks and optionally generate combined images with shape overlays.
Uses convex hull for bounding boxes with configurable padding.
All images are saved as high-quality JPEGs.

Reads from: output_data/2a_parks_concave_hull_analysis.geojson
Outputs to: images/{park_name}/ directories (each park in its own folder)
  - {park_name}.jpg: satellite image
  - {park_name}_combined.jpg: satellite + overlay (if GENERATE_OVERLAY=True)
  - metadata.json: park metadata

Usage:
    python 3_generate_park_images.py
"""

import os
import sys
import json
import math
import requests
import mercantile
import numpy as np
import geopandas as gpd
from PIL import Image, ImageDraw, ImageColor

# Increase PIL's max pixel limit for large parks (default ~178M pixels)
# Safe since we're processing known data, not untrusted uploads
Image.MAX_IMAGE_PIXELS = 1_000_000_000  # 1 billion pixels
from io import BytesIO
from shapely.geometry import shape, box, Polygon, MultiPolygon
from shapely.ops import transform
from shapely import wkt
import pyproj
from rich.console import Console
from rich.progress import track
from dotenv import load_dotenv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# ==============================================================================
# CONFIGURATION CONSTANTS
# ==============================================================================

# Satellite imagery settings
ZOOM_LEVEL = 20  # Zoom level for satellite imagery (1-22, higher = more detail) [18 for testing, 20 for production]
TILE_SIZE = 256  # Standard tile size in pixels

# Padding around park boundaries
PADDING_VALUE = 50  # Amount of padding to add
PADDING_TYPE = "meters"  # Either "meters" or "percent"

# Overlay settings
GENERATE_OVERLAY = (
    True  # Whether to generate transparent overlays (combined only, no separate mask)
)

# Mask settings (area outside the park)
MASK_OVERLAY_COLOR = "#FFFFFF"  # Hex color for the surrounding area
MASK_OVERLAY_OPACITY = 100  # 0-255

# Concave hull stroke settings
CONCAVE_HULL_STROKE_COLOR = "#000000"
CONCAVE_HULL_STROKE_WIDTH = 5
CONCAVE_HULL_STROKE_OPACITY = 200  # 0-255
CONCAVE_HULL_JOINT_SCALE = 0.5  # Ratio of joint circle diameter to stroke width

# JPEG quality setting
JPEG_QUALITY = 95  # JPEG quality (1-100, higher = better quality)

# Parallel download settings
MAX_TILE_WORKERS = 32  # Number of parallel threads for downloading tiles
TILE_RETRY_ATTEMPTS = 5  # Number of retry attempts for failed tile downloads
TILE_RETRY_MIN_WAIT = 1  # Minimum wait time between retries (seconds)
TILE_RETRY_MAX_WAIT = 30  # Maximum wait time between retries (seconds)

# Processing options
SKIP_EXISTING = True  # Skip parks that already have images
DRY_RUN = False  # If True, show statistics without downloading
LIMIT_PARKS = None  # Set to a number to limit processing (e.g., 10), or None for all

# File paths
OUTPUT_DIR = Path("images")
INPUT_GEOJSON = "output_data/2a_parks_concave_hull_analysis.geojson"

# ==============================================================================

# Load environment variables
load_dotenv()

console = Console()

# Get Mapbox token
MAPBOX_ACCESS_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN")


# Validate settings at startup
def validate_settings():
    """Validate configuration settings"""
    if not 1 <= ZOOM_LEVEL <= 22:
        console.print(
            f"[bold red]Error: ZOOM_LEVEL must be between 1 and 22 (got {ZOOM_LEVEL})[/bold red]"
        )
        sys.exit(1)

    if not 0 <= MASK_OVERLAY_OPACITY <= 255:
        console.print(
            f"[bold red]Error: MASK_OVERLAY_OPACITY must be between 0 and 255 (got {MASK_OVERLAY_OPACITY})[/bold red]"
        )
        sys.exit(1)

    if not 0 <= CONCAVE_HULL_STROKE_OPACITY <= 255:
        console.print(
            f"[bold red]Error: CONCAVE_HULL_STROKE_OPACITY must be between 0 and 255 (got {CONCAVE_HULL_STROKE_OPACITY})[/bold red]"
        )
        sys.exit(1)

    if PADDING_TYPE not in ["meters", "percent"]:
        console.print(
            f"[bold red]Error: PADDING_TYPE must be 'meters' or 'percent' (got {PADDING_TYPE})[/bold red]"
        )
        sys.exit(1)

    if not MAPBOX_ACCESS_TOKEN:
        console.print(
            "[bold red]Error: MAPBOX_ACCESS_TOKEN not found in .env file[/bold red]"
        )
        sys.exit(1)

    if not Path(INPUT_GEOJSON).exists():
        console.print(
            f"[bold red]Error: Input file not found: {INPUT_GEOJSON}[/bold red]"
        )
        sys.exit(1)


# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(exist_ok=True)


def format_park_name(park_id, name311):
    """Format park name for filename: id followed by name311 (lowercase, dashed)"""
    if not name311:
        name311 = "unnamed"

    # Convert to lowercase and replace spaces/special characters with dashes
    name_formatted = name311.lower()
    # Replace common special characters and spaces with dashes
    for char in [
        " ",
        "/",
        "\\",
        "(",
        ")",
        ".",
        ",",
        "&",
        "'",
        '"',
        ":",
        ";",
        "!",
        "?",
        "#",
        "@",
        "$",
        "%",
        "^",
        "*",
        "+",
        "=",
        "|",
        "`",
        "~",
        "[",
        "]",
        "{",
        "}",
        "<",
        ">",
    ]:
        name_formatted = name_formatted.replace(char, "-")

    # Remove multiple consecutive dashes
    while "--" in name_formatted:
        name_formatted = name_formatted.replace("--", "-")

    # Remove leading/trailing dashes
    name_formatted = name_formatted.strip("-")

    return f"{park_id}-{name_formatted}"


def expand_bbox(bbox, padding, padding_type="meters"):
    """
    Expand a bounding box by padding

    bbox: (west, south, east, north) in WGS84
    padding: amount to expand by
    padding_type: 'meters' or 'percent'
    """
    west, south, east, north = bbox

    if padding == 0:
        return bbox

    if padding_type == "percent":
        # Calculate percentage based on bbox dimensions
        width = east - west
        height = north - south

        # Expand by percentage
        west_expand = width * (padding / 100)
        east_expand = width * (padding / 100)
        south_expand = height * (padding / 100)
        north_expand = height * (padding / 100)

        return (
            west - west_expand,
            south - south_expand,
            east + east_expand,
            north + north_expand,
        )

    else:  # meters
        # Need to convert meters to degrees
        # This is approximate and varies by latitude

        # For longitude: 1 degree ≈ 111,320 * cos(latitude) meters
        # For latitude: 1 degree ≈ 111,320 meters

        # Use the center latitude for the calculation
        center_lat = (north + south) / 2

        # Convert padding from meters to degrees
        lat_padding = padding / 111320.0  # meters to degrees latitude
        lon_padding = padding / (
            111320.0 * abs(math.cos(math.radians(center_lat)))
        )  # meters to degrees longitude

        return (
            west - lon_padding,
            south - lat_padding,
            east + lon_padding,
            north + lat_padding,
        )


def make_bbox_square(bbox):
    """
    Make a bounding box square by expanding the shorter edge to match the longer edge.
    The expansion is centered so the original content remains in the middle.

    bbox: (west, south, east, north) in WGS84
    Returns: (west, south, east, north) in WGS84
    """
    west, south, east, north = bbox

    # Calculate current dimensions in meters
    width_meters, height_meters = calculate_bbox_dimensions_meters(bbox)

    if abs(width_meters - height_meters) < 0.01:  # Already square (within 1cm)
        return bbox

    # Calculate center point
    center_lat = (north + south) / 2
    center_lon = (east + west) / 2

    if width_meters < height_meters:
        # Need to expand width to match height
        diff_meters = (height_meters - width_meters) / 2
        # Convert meters to degrees longitude at this latitude
        lon_expand = diff_meters / (111320.0 * abs(math.cos(math.radians(center_lat))))
        west -= lon_expand
        east += lon_expand
    else:
        # Need to expand height to match width
        diff_meters = (width_meters - height_meters) / 2
        # Convert meters to degrees latitude
        lat_expand = diff_meters / 111320.0
        south -= lat_expand
        north += lat_expand

    return (west, south, east, north)


def get_convex_hull_bbox(geometry):
    """Get bounding box of the convex hull of a geometry in WGS84"""
    # Ensure we have a valid geometry
    if geometry.is_empty:
        return None

    # Get convex hull
    convex_hull = geometry.convex_hull

    # Get bounds (minx, miny, maxx, maxy)
    bounds = convex_hull.bounds

    return bounds  # (west, south, east, north) in WGS84


def calculate_bbox_dimensions_meters(bbox):
    """Calculate width and height of a bounding box in meters"""
    west, south, east, north = bbox

    # Use the center latitude for more accurate calculations
    center_lat = (north + south) / 2

    # Calculate width (longitude difference)
    # At the given latitude, 1 degree longitude = 111320 * cos(lat) meters
    lon_diff = east - west
    width_meters = lon_diff * 111320.0 * abs(math.cos(math.radians(center_lat)))

    # Calculate height (latitude difference)
    # 1 degree latitude = 111320 meters (approximately)
    lat_diff = north - south
    height_meters = lat_diff * 111320.0

    return width_meters, height_meters


def extract_geometry_vertices_latlon(geometry):
    """Extract vertices from a geometry as lat/lon coordinates

    Returns a list of polygons, where each polygon is a dictionary with:
    - exterior: list of [lon, lat] coordinates
    - interiors: list of holes, each being a list of [lon, lat] coordinates
    """
    polygons = []

    if isinstance(geometry, Polygon):
        # Single polygon
        polygon_data = {
            "exterior": [[x, y] for x, y in geometry.exterior.coords],
            "interiors": [
                [[x, y] for x, y in interior.coords] for interior in geometry.interiors
            ],
        }
        polygons.append(polygon_data)

    elif isinstance(geometry, MultiPolygon):
        # Multiple polygons
        for polygon in geometry.geoms:
            polygon_data = {
                "exterior": [[x, y] for x, y in polygon.exterior.coords],
                "interiors": [
                    [[x, y] for x, y in interior.coords]
                    for interior in polygon.interiors
                ],
            }
            polygons.append(polygon_data)

    return polygons


def extract_geometry_vertices_pixels(geometry, bbox, img_width, img_height):
    """Extract vertices from a geometry as pixel coordinates

    Returns a list of polygons, where each polygon is a dictionary with:
    - exterior: list of [x, y] pixel coordinates
    - interiors: list of holes, each being a list of [x, y] pixel coordinates
    """
    west, south, east, north = bbox

    # Convert bbox corners to mercator
    west_merc, north_merc = mercantile.xy(west, north)
    east_merc, south_merc = mercantile.xy(east, south)

    # Calculate the mercator bounds of the cropped area
    merc_width = east_merc - west_merc
    merc_height = north_merc - south_merc

    def lonlat_to_pixel(lon, lat):
        """Convert a single lon/lat coordinate to pixel coordinates"""
        # Convert to mercator
        merc_x, merc_y = mercantile.xy(lon, lat)

        # Convert to pixel coordinates relative to the cropped bbox
        pixel_x = (merc_x - west_merc) / merc_width * img_width
        pixel_y = (north_merc - merc_y) / merc_height * img_height

        return [round(pixel_x, 2), round(pixel_y, 2)]

    polygons = []

    if isinstance(geometry, Polygon):
        # Single polygon
        polygon_data = {
            "exterior": [lonlat_to_pixel(x, y) for x, y in geometry.exterior.coords],
            "interiors": [
                [lonlat_to_pixel(x, y) for x, y in interior.coords]
                for interior in geometry.interiors
            ],
        }
        polygons.append(polygon_data)

    elif isinstance(geometry, MultiPolygon):
        # Multiple polygons
        for polygon in geometry.geoms:
            polygon_data = {
                "exterior": [lonlat_to_pixel(x, y) for x, y in polygon.exterior.coords],
                "interiors": [
                    [lonlat_to_pixel(x, y) for x, y in interior.coords]
                    for interior in polygon.interiors
                ],
            }
            polygons.append(polygon_data)

    return polygons


def save_park_metadata(
    park_dir,
    park_id,
    name311,
    original_bbox,
    padded_bbox,
    image_width_px,
    image_height_px,
    original_geometry=None,
    concave_hull_geometry=None,
    has_overlay=False,
):
    """Save metadata for a park as JSON, including polygon vertices"""
    width_meters, height_meters = calculate_bbox_dimensions_meters(padded_bbox)

    park_name = format_park_name(park_id, name311)

    metadata = {
        "park_id": park_id,
        "name311": name311,
        "original_bbox": {
            "west": original_bbox[0],
            "south": original_bbox[1],
            "east": original_bbox[2],
            "north": original_bbox[3],
        },
        "padded_bbox": {
            "west": padded_bbox[0],
            "south": padded_bbox[1],
            "east": padded_bbox[2],
            "north": padded_bbox[3],
        },
        "width_meters": round(width_meters, 2),
        "height_meters": round(height_meters, 2),
        "image_dimensions": {"width_px": image_width_px, "height_px": image_height_px},
        "files": {"satellite": f"{park_name}.jpg"},
    }

    # Add original geometry vertices if provided
    if original_geometry:
        metadata["original_geometry"] = {
            "lat_lon": extract_geometry_vertices_latlon(original_geometry),
            "pixels": extract_geometry_vertices_pixels(
                original_geometry, padded_bbox, image_width_px, image_height_px
            ),
        }

    # Add concave hull vertices if provided
    if concave_hull_geometry:
        metadata["concave_hull"] = {
            "lat_lon": extract_geometry_vertices_latlon(concave_hull_geometry),
            "pixels": extract_geometry_vertices_pixels(
                concave_hull_geometry, padded_bbox, image_width_px, image_height_px
            ),
        }

    if has_overlay:
        metadata["files"]["combined"] = f"{park_name}_combined.jpg"

    # Save metadata
    metadata_path = park_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return metadata_path


def get_concave_hull_geometry(park):
    """Extract concave hull geometry from park data"""
    # The concave hull should be stored in the 'concave_hull_polygon' field
    if "concave_hull_polygon" in park and park["concave_hull_polygon"]:
        try:
            # Check if it's a string that needs parsing
            if isinstance(park["concave_hull_polygon"], str):
                # Try to parse as JSON first (GeoJSON format)
                import json

                try:
                    geojson = json.loads(park["concave_hull_polygon"])
                    from shapely.geometry import shape

                    return shape(geojson)
                except json.JSONDecodeError:
                    # If not JSON, try WKT format
                    return wkt.loads(park["concave_hull_polygon"])
            else:
                # If it's already a geometry object
                return park["concave_hull_polygon"]
        except Exception as e:
            print(f"Error parsing concave hull polygon for park {park[':id']}: {e}")
            pass

    # Fallback to the main geometry (which should already be the concave hull)
    return park.geometry


def download_and_stitch_tiles(bbox, zoom, park_name, park_dir, skip_existing=True):
    """
    Download tiles for a bounding box and stitch them together, then crop to exact bbox

    bbox: (west, south, east, north) in WGS84
    zoom: int zoom level
    park_name: formatted name for the output file
    park_dir: directory for this park's files
    skip_existing: if True, skip downloading if file already exists
    """
    output_path = park_dir / f"{park_name}.jpg"

    # Skip if file already exists and skip_existing is True
    if skip_existing and output_path.exists():
        console.print(f"[yellow]Skipping {park_name} (already exists)[/yellow]")
        return None

    west, south, east, north = bbox

    # Get all tiles that intersect the bbox
    tiles = list(mercantile.tiles(west, south, east, north, zoom))

    if not tiles:
        console.print(f"[red]No tiles found for {park_name}[/red]")
        return None

    # Calculate grid dimensions
    xs = [t.x for t in tiles]
    ys = [t.y for t in tiles]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    # Create full tiles image
    full_width = (x_max - x_min + 1) * TILE_SIZE
    full_height = (y_max - y_min + 1) * TILE_SIZE
    full_img = Image.new("RGB", (full_width, full_height))

    # Mapbox tile URL template
    tile_url_template = (
        "https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}.jpg?access_token="
        + MAPBOX_ACCESS_TOKEN
    )

    @retry(
        stop=stop_after_attempt(TILE_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=1, min=TILE_RETRY_MIN_WAIT, max=TILE_RETRY_MAX_WAIT
        ),
        retry=retry_if_exception_type((requests.RequestException, IOError)),
        reraise=True,
    )
    def download_tile_with_retry(tile):
        """Download a single tile with retry logic. Raises exception on failure."""
        url = tile_url_template.format(z=tile.z, x=tile.x, y=tile.y)
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return (tile, response.content)

    def download_tile(tile):
        """Download a single tile, return (tile, image_data) or (tile, None, error_msg) on failure"""
        try:
            return download_tile_with_retry(tile)
        except Exception as e:
            return (tile, None, str(e))

    # Download tiles in parallel
    tile_results = []
    with ThreadPoolExecutor(max_workers=MAX_TILE_WORKERS) as executor:
        futures = {executor.submit(download_tile, tile): tile for tile in tiles}
        for future in as_completed(futures):
            tile_results.append(future.result())

    # Check for any failed tiles - if any failed, abort without stitching
    failed_tiles = [r for r in tile_results if len(r) == 3]
    if failed_tiles:
        for tile, _, error_msg in failed_tiles:
            console.print(
                f"[red]Failed to download tile {tile.x},{tile.y} for {park_name} after {TILE_RETRY_ATTEMPTS} retries: {error_msg}[/red]"
            )
        console.print(
            f"[red]✗ Skipping {park_name} due to {len(failed_tiles)} failed tile(s)[/red]"
        )
        return None

    # All tiles downloaded successfully - paste them onto the full image
    for tile, image_data in tile_results:
        img = Image.open(BytesIO(image_data))

        # Calculate position in full image
        x_offset = (tile.x - x_min) * TILE_SIZE
        y_offset = (tile.y - y_min) * TILE_SIZE

        full_img.paste(img, (x_offset, y_offset))

    # Now crop to the exact bounding box
    # Convert lat/lon bbox to pixel coordinates within the full image

    # Get the bounds of the tiles in mercator coordinates
    tiles_bounds = mercantile.xy_bounds(x_min, y_min, zoom)
    tiles_bounds_max = mercantile.xy_bounds(x_max + 1, y_max + 1, zoom)

    merc_width = tiles_bounds_max.left - tiles_bounds.left
    merc_height = tiles_bounds.top - tiles_bounds_max.top

    # Convert bbox corners to mercator
    west_merc, north_merc = mercantile.xy(west, north)
    east_merc, south_merc = mercantile.xy(east, south)

    # Convert to pixel coordinates
    crop_left = int((west_merc - tiles_bounds.left) / merc_width * full_width)
    crop_right = int((east_merc - tiles_bounds.left) / merc_width * full_width)
    crop_top = int((tiles_bounds.top - north_merc) / merc_height * full_height)
    crop_bottom = int((tiles_bounds.top - south_merc) / merc_height * full_height)

    # Ensure crop bounds are within image bounds
    crop_left = max(0, crop_left)
    crop_right = min(full_width, crop_right)
    crop_top = max(0, crop_top)
    crop_bottom = min(full_height, crop_bottom)

    # Crop the image to exact bounding box
    cropped_img = full_img.crop((crop_left, crop_top, crop_right, crop_bottom))

    # Convert to RGB if needed (JPEG doesn't support RGBA)
    if cropped_img.mode == "RGBA":
        cropped_img = cropped_img.convert("RGB")

    # Create park directory only when we're about to save (avoids empty folders on termination)
    park_dir.mkdir(exist_ok=True)

    # Save the cropped image as high-quality JPEG
    width, height = cropped_img.size
    cropped_img.save(output_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    console.print(
        f"[green]✓ Saved {park_name}.jpg ({width}x{height} pixels, from {len(tiles)} tiles)[/green]"
    )

    return cropped_img


def geometry_to_pixel_coords(geometry, bbox, img_width, img_height):
    """Convert a shapely geometry to pixel coordinates for a cropped image"""
    west, south, east, north = bbox

    # Convert bbox corners to mercator
    west_merc, north_merc = mercantile.xy(west, north)
    east_merc, south_merc = mercantile.xy(east, south)

    # Calculate the mercator bounds of the cropped area
    merc_width = east_merc - west_merc
    merc_height = north_merc - south_merc

    def coords_to_pixels(coords):
        """Convert a list of (lon, lat) coordinates to pixel coordinates"""
        pixels = []
        for lon, lat in coords:
            # Convert to mercator
            merc_x, merc_y = mercantile.xy(lon, lat)

            # Convert to pixel coordinates relative to the cropped bbox
            pixel_x = (merc_x - west_merc) / merc_width * img_width
            pixel_y = (north_merc - merc_y) / merc_height * img_height

            pixels.append((int(pixel_x), int(pixel_y)))

        return pixels

    # Handle different geometry types
    if isinstance(geometry, Polygon):
        # Get exterior coordinates
        exterior = coords_to_pixels(geometry.exterior.coords)
        # Get interior (holes) coordinates
        interiors = [
            coords_to_pixels(interior.coords) for interior in geometry.interiors
        ]
        return [exterior] + interiors

    elif isinstance(geometry, MultiPolygon):
        all_polygons = []
        for polygon in geometry.geoms:
            exterior = coords_to_pixels(polygon.exterior.coords)
            interiors = [
                coords_to_pixels(interior.coords) for interior in polygon.interiors
            ]
            all_polygons.extend([exterior] + interiors)
        return all_polygons

    else:
        return []


def create_park_overlay(
    park_name, park_geometry, concave_hull_geometry, bbox, park_dir
):
    """Create an overlay image with transparent park area and white overlay outside"""

    # Check if satellite image exists
    input_path = park_dir / f"{park_name}.jpg"
    if not input_path.exists():
        console.print(
            f"[yellow]Satellite image not found for {park_name}, skipping overlay[/yellow]"
        )
        return None

    # Load the satellite image to get dimensions
    satellite_img = Image.open(input_path)
    img_width, img_height = satellite_img.size

    # Create a new RGBA image (transparent background)
    overlay_img = Image.new("RGBA", (img_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_img)

    # First, fill the entire image with the mask color
    mask_rgb = ImageColor.getrgb(MASK_OVERLAY_COLOR)
    draw.rectangle([(0, 0), (img_width, img_height)], fill=mask_rgb + (255,))

    # Convert park geometry to pixel coordinates (using extract_geometry_vertices_pixels for correct hole handling)
    park_polygons = extract_geometry_vertices_pixels(
        park_geometry, bbox, img_width, img_height
    )

    if not park_polygons:
        console.print(
            f"[red]Could not convert geometry to pixels for {park_name}[/red]"
        )
        return None

    # Create a mask for the park area
    mask = Image.new("L", (img_width, img_height), 0)
    mask_draw = ImageDraw.Draw(mask)

    # Draw the park area on the mask (handle multiple polygons with holes)
    for poly in park_polygons:
        # Draw exterior (white)
        ext_coords = [tuple(p) for p in poly["exterior"]]
        if len(ext_coords) >= 3:
            mask_draw.polygon(ext_coords, fill=255)

        # Draw interiors/holes (black)
        for hole in poly["interiors"]:
            hole_coords = [tuple(p) for p in hole]
            if len(hole_coords) >= 3:
                mask_draw.polygon(hole_coords, fill=0)

    # Apply the mask to make the park area transparent
    # Where mask is 255 (park), alpha becomes 0
    # Where mask is 0 (outside), alpha becomes MASK_OVERLAY_OPACITY
    overlay_img.putalpha(
        Image.composite(
            Image.new("L", (img_width, img_height), 0),  # Transparent for park area
            Image.new(
                "L", (img_width, img_height), MASK_OVERLAY_OPACITY
            ),  # Semi-transparent for outside
            mask,
        )
    )

    # Draw concave hull stroke on top
    if concave_hull_geometry:
        hull_polygons = extract_geometry_vertices_pixels(
            concave_hull_geometry, bbox, img_width, img_height
        )

        if hull_polygons:
            stroke_rgb = ImageColor.getrgb(CONCAVE_HULL_STROKE_COLOR)
            stroke_rgba = stroke_rgb + (CONCAVE_HULL_STROKE_OPACITY,)

            draw = ImageDraw.Draw(overlay_img)

            # Calculate joint radius
            joint_radius = (CONCAVE_HULL_STROKE_WIDTH * CONCAVE_HULL_JOINT_SCALE) / 2.0

            for poly in hull_polygons:
                # Draw exterior stroke
                ext_coords = [tuple(p) for p in poly["exterior"]]
                if len(ext_coords) >= 2:
                    # Close loop if needed
                    if ext_coords[0] != ext_coords[-1]:
                        ext_coords.append(ext_coords[0])
                    draw.line(
                        ext_coords, fill=stroke_rgba, width=CONCAVE_HULL_STROKE_WIDTH
                    )

                    # Draw joints at each vertex
                    for x, y in ext_coords:
                        draw.ellipse(
                            [
                                (x - joint_radius, y - joint_radius),
                                (x + joint_radius, y + joint_radius),
                            ],
                            fill=stroke_rgba,
                        )

                # Draw interior strokes if desired
                for hole in poly["interiors"]:
                    hole_coords = [tuple(p) for p in hole]
                    if len(hole_coords) >= 2:
                        if hole_coords[0] != hole_coords[-1]:
                            hole_coords.append(hole_coords[0])
                        draw.line(
                            hole_coords,
                            fill=stroke_rgba,
                            width=CONCAVE_HULL_STROKE_WIDTH,
                        )

                        # Draw joints at each vertex
                        for x, y in hole_coords:
                            draw.ellipse(
                                [
                                    (x - joint_radius, y - joint_radius),
                                    (x + joint_radius, y + joint_radius),
                                ],
                                fill=stroke_rgba,
                            )

    return overlay_img


def create_combined_image(park_name, park_dir, overlay_img):
    """Create a combined image with satellite + overlay for visualization

    Args:
        park_name: formatted park name
        park_dir: directory for this park's files
        overlay_img: PIL Image object of the overlay (not saved to disk)
    """
    satellite_path = park_dir / f"{park_name}.jpg"

    if not satellite_path.exists():
        return None

    # Load satellite image
    satellite_img = Image.open(satellite_path).convert("RGBA")

    # Composite overlay on top of satellite
    combined = Image.alpha_composite(satellite_img, overlay_img)

    # Convert to RGB for JPEG
    combined_rgb = combined.convert("RGB")

    # Save combined image as high-quality JPEG
    combined_path = park_dir / f"{park_name}_combined.jpg"
    combined_rgb.save(combined_path, "JPEG", quality=JPEG_QUALITY, optimize=True)

    return combined_path


def main():
    """Main function to process all parks"""
    # Validate settings first
    validate_settings()

    console.print("[bold cyan]NYC Park Image Generator[/bold cyan]")
    console.print("[cyan]Configuration:[/cyan]")
    console.print(f"  Zoom level: {ZOOM_LEVEL}")
    console.print(f"  Output directory: {OUTPUT_DIR}")

    if PADDING_VALUE > 0:
        console.print(f"  Padding: {PADDING_VALUE} {PADDING_TYPE}")

    if GENERATE_OVERLAY:
        console.print(
            f"  Combined images: ENABLED (mask opacity: {MASK_OVERLAY_OPACITY}/255, stroke opacity: {CONCAVE_HULL_STROKE_OPACITY}/255)"
        )
    else:
        console.print(f"  Combined images: DISABLED")

    if LIMIT_PARKS:
        console.print(f"  Limit: First {LIMIT_PARKS} parks")

    if SKIP_EXISTING:
        console.print(f"  Skip existing: ENABLED")

    if DRY_RUN:
        console.print(f"[yellow]  DRY RUN MODE - No images will be downloaded[/yellow]")

    # Load the GeoJSON file
    console.print("\n[bold]Loading park data...[/bold]")
    gdf = gpd.read_file(INPUT_GEOJSON)

    # Filter out parks with invalid geometries
    valid_parks = gdf[~gdf.geometry.is_empty & gdf.geometry.is_valid]
    console.print(
        f"[green]Found {len(valid_parks)} valid parks out of {len(gdf)} total[/green]"
    )

    # Sort by area (smallest first)
    valid_parks = valid_parks.sort_values("area_sqm", ascending=True)

    # Apply limit if specified
    if LIMIT_PARKS:
        valid_parks = valid_parks.head(LIMIT_PARKS)
        console.print(
            f"[yellow]Processing only first {LIMIT_PARKS} smallest parks[/yellow]"
        )

    # Process each park
    if DRY_RUN:
        console.print(
            f"\n[bold]Analyzing tile requirements at zoom level {ZOOM_LEVEL}...[/bold]"
        )
        total_tiles = 0
        park_tile_counts = []
    else:
        console.print(f"\n[bold]Processing parks at zoom level {ZOOM_LEVEL}...[/bold]")

    success_count = 0
    overlay_count = 0
    error_count = 0
    skipped_count = 0

    for idx, park in track(
        valid_parks.iterrows(), total=len(valid_parks), description="Processing parks"
    ):
        park_id = park[":id"]
        name311 = park.get("name311", "unnamed")

        # Format the filename
        park_name = format_park_name(park_id, name311)

        # Define park-specific directory (don't create yet - wait until download succeeds)
        park_dir = OUTPUT_DIR / park_name

        # Check if file already exists
        output_path = park_dir / f"{park_name}.jpg"
        if SKIP_EXISTING and output_path.exists():
            # If generating overlays, still process overlay even if image exists
            if GENERATE_OVERLAY and not DRY_RUN:
                combined_path = park_dir / f"{park_name}_combined.jpg"
                if not combined_path.exists():
                    # Get geometries
                    concave_hull = get_concave_hull_geometry(park)
                    original_bbox = get_convex_hull_bbox(park.geometry)
                    if original_bbox and concave_hull and not concave_hull.is_empty:
                        padded_bbox = expand_bbox(
                            original_bbox, PADDING_VALUE, PADDING_TYPE
                        )
                        padded_bbox = make_bbox_square(padded_bbox)
                        try:
                            overlay_img = create_park_overlay(
                                park_name,
                                park.geometry,
                                concave_hull,
                                padded_bbox,
                                park_dir,
                            )
                            if overlay_img:
                                # Create combined image directly without saving overlay
                                create_combined_image(park_name, park_dir, overlay_img)

                                # Get image dimensions
                                satellite_img = Image.open(output_path)
                                img_width, img_height = satellite_img.size

                                # Save metadata
                                save_park_metadata(
                                    park_dir,
                                    park_id,
                                    name311,
                                    original_bbox,
                                    padded_bbox,
                                    img_width,
                                    img_height,
                                    original_geometry=park.geometry,
                                    concave_hull_geometry=concave_hull,
                                    has_overlay=True,
                                )

                                overlay_count += 1
                                console.print(
                                    f"[green]✓ Created combined image for existing: {park_name}[/green]"
                                )
                        except Exception as e:
                            console.print(
                                f"[red]Error creating overlay for {park_name}: {e}[/red]"
                            )

            skipped_count += 1
            continue

        # Get convex hull bounding box
        original_bbox = get_convex_hull_bbox(park.geometry)

        if original_bbox is None:
            console.print(f"[red]Invalid geometry for park {park_id} ({name311})[/red]")
            error_count += 1
            continue

        # Apply padding to the bounding box and make it square
        padded_bbox = expand_bbox(original_bbox, PADDING_VALUE, PADDING_TYPE)
        padded_bbox = make_bbox_square(padded_bbox)

        # In dry-run mode, just count tiles
        if DRY_RUN:
            west, south, east, north = padded_bbox
            tiles = list(mercantile.tiles(west, south, east, north, ZOOM_LEVEL))
            tile_count = len(tiles)
            total_tiles += tile_count
            park_tile_counts.append((park_name, tile_count))
            continue

        # Download and stitch tiles
        try:
            result = download_and_stitch_tiles(
                padded_bbox,
                ZOOM_LEVEL,
                park_name,
                park_dir,
                skip_existing=SKIP_EXISTING,
            )
            if result:
                success_count += 1

                # Get image dimensions
                img_width, img_height = result.size

                # Get concave hull for metadata and overlay
                concave_hull = get_concave_hull_geometry(park)

                # Generate overlay if requested
                if GENERATE_OVERLAY:
                    if concave_hull and not concave_hull.is_empty:
                        try:
                            overlay_img = create_park_overlay(
                                park_name,
                                park.geometry,
                                concave_hull,
                                padded_bbox,
                                park_dir,
                            )
                            if overlay_img:
                                # Create combined image directly without saving overlay
                                create_combined_image(park_name, park_dir, overlay_img)
                                overlay_count += 1
                                console.print(
                                    f"[green]✓ Created combined image for {park_name}[/green]"
                                )
                        except Exception as e:
                            console.print(
                                f"[red]Error creating overlay for {park_name}: {e}[/red]"
                            )

                # Save metadata
                save_park_metadata(
                    park_dir,
                    park_id,
                    name311,
                    original_bbox,
                    padded_bbox,
                    img_width,
                    img_height,
                    original_geometry=park.geometry,
                    concave_hull_geometry=concave_hull,
                    has_overlay=GENERATE_OVERLAY,
                )

            elif SKIP_EXISTING and output_path.exists():
                skipped_count += 1
        except Exception as e:
            console.print(
                f"[red]Error processing park {park_id} ({name311}): {e}[/red]"
            )
            error_count += 1

    # Summary
    if DRY_RUN:
        console.print("\n[bold cyan]Dry Run Analysis Complete![/bold cyan]")
        console.print(f"[cyan]Total parks to process: {len(valid_parks)}[/cyan]")
        console.print(f"[cyan]Total tiles needed: {total_tiles:,}[/cyan]")
        console.print(
            f"[cyan]Estimated download size: ~{(total_tiles * 50) / 1024:.1f} MB[/cyan]"
        )  # Assume ~50KB per tile
        console.print(
            f"[cyan]Estimated time: ~{total_tiles * 0.2 / 60:.1f} minutes[/cyan]"
        )  # Assume ~0.2s per tile

        # Show parks with most tiles
        if park_tile_counts:
            park_tile_counts.sort(key=lambda x: x[1], reverse=True)
            console.print("\n[bold]Top 5 parks by tile count:[/bold]")
            for park_name, tile_count in park_tile_counts[:5]:
                console.print(f"  {park_name}: {tile_count} tiles")
    else:
        console.print("\n[bold cyan]Processing Complete![/bold cyan]")
        console.print(f"[green]Successfully downloaded: {success_count} images[/green]")
        if GENERATE_OVERLAY:
            console.print(
                f"[green]Successfully created: {overlay_count} combined images[/green]"
            )
        if SKIP_EXISTING:
            console.print(
                f"[yellow]Skipped (already exist): {skipped_count} images[/yellow]"
            )
        console.print(f"[red]Errors: {error_count} parks[/red]")
        console.print(f"[cyan]Total processed: {len(valid_parks)} parks[/cyan]")


if __name__ == "__main__":
    main()
