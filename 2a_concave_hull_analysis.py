"""
NYC Parks Concave Hull Analysis
Analyze geometric properties of the concave hulls for NYC parks
"""

import json
import math
import geopandas as gpd
import numpy as np
from shapely import geometry
from shapely.geometry import shape, mapping, Polygon
from shapely.ops import transform
import pyproj

print("Loading NYC Parks with Concave Hulls...")
SOURCE_DATA_FILE = "./output_data/1a_parks_with_concave_hulls.geojson"
OUTPUT_DATA_FILE = "./output_data/2a_parks_concave_hull_analysis.geojson"

# Load the parks data with concave hulls
with open(SOURCE_DATA_FILE, "r") as f:
    data = json.load(f)

print(f"Loaded {len(data['features'])} parks")

# Create transformer for accurate measurements in meters (WGS84 to UTM Zone 18N)
transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)

# MARK: Circle Analysis - Compactness Metrics

print("\nCalculating circle analysis (compactness metrics)...")

for feature in data["features"]:
    properties = feature["properties"]

    # Get the concave hull polygon
    concave_hull_dict = properties.get("concave_hull_polygon")
    if not concave_hull_dict:
        # Skip if no concave hull
        properties["ca_ch_area_sqm"] = None
        properties["ca_ch_perimeter_m"] = None
        properties["ca_polsby_popper"] = None
        properties["ca_schwartzberg"] = None
        properties["ca_reock_compactness"] = None
        properties["ca_circumscribed_circle_radius"] = None
        properties["ca_circumscribed_circle_area"] = None
        continue

    # Convert to shapely geometry
    concave_hull = shape(concave_hull_dict)

    # Project to UTM for accurate metric measurements
    concave_hull_proj = transform(transformer.transform, concave_hull)

    # Calculate area and perimeter of concave hull
    ch_area = concave_hull_proj.area
    ch_perimeter = concave_hull_proj.length

    properties["ca_ch_area_sqm"] = ch_area
    properties["ca_ch_perimeter_m"] = ch_perimeter

    # Polsby-Popper Compactness: 4π * Area / Perimeter²
    # Ranges from 0 to 1, where 1 is a perfect circle
    if ch_perimeter > 0:
        polsby_popper = (4 * math.pi * ch_area) / (ch_perimeter**2)
        properties["ca_polsby_popper"] = polsby_popper
    else:
        properties["ca_polsby_popper"] = None

    # Schwartzberg Compactness (Reciprocal of Reock): Perimeter / (2π√(Area/π))
    # Equal to 1 for a circle, increases for less compact shapes
    if ch_area > 0:
        schwartzberg = ch_perimeter / (2 * math.pi * math.sqrt(ch_area / math.pi))
        properties["ca_schwartzberg"] = schwartzberg
    else:
        properties["ca_schwartzberg"] = None

    # Reock Compactness: Area / Area of minimum bounding circle
    # The minimum bounding circle is calculated from the convex hull
    try:
        # Get the minimum bounding circle (available in shapely 2.0+)
        min_circle = concave_hull_proj.minimum_bounding_circle()
        min_circle_area = min_circle.area
    except AttributeError:
        # Fallback: use convex hull's minimum bounding circle
        # or approximate using the envelope
        convex_hull = concave_hull_proj.convex_hull
        # Use the circumradius of the convex hull as approximation
        # Get the bounds and calculate the diagonal
        bounds = convex_hull.bounds
        center_x = (bounds[0] + bounds[2]) / 2
        center_y = (bounds[1] + bounds[3]) / 2

        # Find the maximum distance from center to any vertex
        if isinstance(convex_hull, Polygon):
            coords = list(convex_hull.exterior.coords)
        else:
            coords = []

        max_dist = 0
        for x, y in coords:
            dist = math.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
            if dist > max_dist:
                max_dist = dist

        # Area of circle with this radius
        min_circle_area = math.pi * (max_dist**2) if max_dist > 0 else 0

    if min_circle_area > 0:
        reock_compactness = ch_area / min_circle_area
        properties["ca_reock_compactness"] = reock_compactness

        # Calculate the radius of the circumscribed circle
        # Area = π * r², so r = √(Area/π)
        circumscribed_radius = math.sqrt(min_circle_area / math.pi)
        properties["ca_circumscribed_circle_radius"] = circumscribed_radius
        properties["ca_circumscribed_circle_area"] = min_circle_area
    else:
        properties["ca_reock_compactness"] = None
        properties["ca_circumscribed_circle_radius"] = None
        properties["ca_circumscribed_circle_area"] = None

print(f"  Added circle analysis fields (ca_ prefix):")
print(f"    - ca_ch_area_sqm: Concave hull area in square meters")
print(f"    - ca_ch_perimeter_m: Concave hull perimeter in meters")
print(f"    - ca_polsby_popper: Polsby-Popper compactness (0-1, 1=circle)")
print(
    f"    - ca_schwartzberg: Schwartzberg compactness (1=circle, higher=less compact)"
)
print(f"    - ca_reock_compactness: Reock compactness (0-1, 1=circle)")
print(f"    - ca_circumscribed_circle_radius: Radius of minimum bounding circle (m)")
print(f"    - ca_circumscribed_circle_area: Area of minimum bounding circle (m²)")

# MARK: Rectangularity Analysis - Minimum Rotated Rectangle

print("\nCalculating rectangularity analysis (minimum rotated rectangle)...")

for feature in data["features"]:
    properties = feature["properties"]

    # Get the concave hull polygon
    concave_hull_dict = properties.get("concave_hull_polygon")
    if not concave_hull_dict:
        # Skip if no concave hull
        properties["ra_mrr_vertices"] = None
        properties["ra_mrr_width"] = None
        properties["ra_mrr_height"] = None
        properties["ra_mrr_rotation_degrees"] = None
        properties["ra_mrr_area_sqm"] = None
        properties["ra_mrr_area_ratio"] = None
        properties["ra_rectangularity"] = None
        properties["ra_mrr_original_ratio"] = None
        continue

    # Convert to shapely geometry
    concave_hull = shape(concave_hull_dict)

    # Project to UTM for accurate metric measurements
    concave_hull_proj = transform(transformer.transform, concave_hull)

    # Calculate minimum rotated rectangle
    mrr = concave_hull_proj.minimum_rotated_rectangle

    # Get the vertices of the minimum rotated rectangle in UTM
    mrr_coords_utm = list(mrr.exterior.coords)

    # Transform vertices back to WGS84 for storage
    transformer_inv = pyproj.Transformer.from_crs(
        "EPSG:32618", "EPSG:4326", always_xy=True
    )
    mrr_coords_wgs84 = [
        list(transformer_inv.transform(x, y)) for x, y in mrr_coords_utm
    ]
    properties["ra_mrr_vertices"] = mrr_coords_wgs84

    # Calculate width and height
    # The MRR has 5 coordinates (last == first), so we have 4 unique vertices
    coords = mrr_coords_utm[:-1]  # Remove duplicate last point

    if len(coords) >= 4:
        # Calculate edge lengths
        edge1 = math.sqrt(
            (coords[1][0] - coords[0][0]) ** 2 + (coords[1][1] - coords[0][1]) ** 2
        )
        edge2 = math.sqrt(
            (coords[2][0] - coords[1][0]) ** 2 + (coords[2][1] - coords[1][1]) ** 2
        )

        # Width is the longer edge, height is the shorter
        mrr_width = max(edge1, edge2)
        mrr_height = min(edge1, edge2)

        properties["ra_mrr_width"] = mrr_width
        properties["ra_mrr_height"] = mrr_height

        # Calculate rotation angle (angle of the longer edge from horizontal)
        # Determine which edge is the width
        if edge1 > edge2:
            dx = coords[1][0] - coords[0][0]
            dy = coords[1][1] - coords[0][1]
        else:
            dx = coords[2][0] - coords[1][0]
            dy = coords[2][1] - coords[1][1]

        # Calculate angle in degrees (counterclockwise from east/positive x-axis)
        rotation_radians = math.atan2(dy, dx)
        rotation_degrees = math.degrees(rotation_radians)

        # Normalize to [0, 180) since rectangles have 180-degree symmetry
        if rotation_degrees < 0:
            rotation_degrees += 180
        elif rotation_degrees >= 180:
            rotation_degrees -= 180

        properties["ra_mrr_rotation_degrees"] = rotation_degrees
    else:
        properties["ra_mrr_width"] = None
        properties["ra_mrr_height"] = None
        properties["ra_mrr_rotation_degrees"] = None

    # Calculate area of MRR
    mrr_area = mrr.area
    properties["ra_mrr_area_sqm"] = mrr_area

    # Area ratio: ratio of concave hull area to MRR area
    ch_area = concave_hull_proj.area
    if mrr_area > 0:
        area_ratio = ch_area / mrr_area
        properties["ra_mrr_area_ratio"] = area_ratio

        # Normalized rectangularity score (0-1, where 1 is most rectangular)
        # If ratio is 0-1, keep as is; if > 1, take inverse
        if area_ratio <= 1:
            rectangularity = area_ratio
        else:
            rectangularity = 1 / area_ratio
        properties["ra_rectangularity"] = rectangularity
    else:
        properties["ra_mrr_area_ratio"] = None
        properties["ra_rectangularity"] = None

    # Ratio of original multipolygon area to MRR area
    original_area = properties.get("area_sqm")
    if original_area is not None and mrr_area > 0:
        original_ratio = original_area / mrr_area
        properties["ra_mrr_original_ratio"] = original_ratio
    else:
        properties["ra_mrr_original_ratio"] = None

print(f"  Added rectangularity analysis fields (ra_ prefix):")
print(f"    - ra_mrr_vertices: Vertices of minimum rotated rectangle (WGS84)")
print(f"    - ra_mrr_width: Width of MRR in meters (longer edge)")
print(f"    - ra_mrr_height: Height of MRR in meters (shorter edge)")
print(f"    - ra_mrr_rotation_degrees: Rotation angle in degrees [0, 180)")
print(f"    - ra_mrr_area_sqm: Area of MRR in square meters")
print(f"    - ra_mrr_area_ratio: Ratio of concave hull area to MRR area")
print(f"    - ra_rectangularity: Normalized rectangularity score (0-1, 1=rectangular)")
print(f"    - ra_mrr_original_ratio: Ratio of original area to MRR area")

# MARK: Triangularity Analysis - Douglas-Peucker Simplification

print("\nCalculating triangularity analysis (Douglas-Peucker simplification)...")

for feature in data["features"]:
    properties = feature["properties"]

    # Get the concave hull polygon
    concave_hull_dict = properties.get("concave_hull_polygon")
    if not concave_hull_dict:
        # Skip if no concave hull
        properties["ta_triangle_vertices"] = None
        properties["ta_triangle_area_sqm"] = None
        properties["ta_triangle_perimeter_m"] = None
        properties["ta_triangle_area_ratio"] = None
        properties["ta_triangularity"] = None
        properties["ta_dp_tolerance"] = None
        properties["ta_triangle_edge_lengths"] = None
        properties["ta_triangle_num_vertices"] = None
        properties["ta_triangle_regularity"] = None
        continue

    # Convert to shapely geometry
    concave_hull = shape(concave_hull_dict)

    # Project to UTM for accurate metric measurements
    concave_hull_proj = transform(transformer.transform, concave_hull)

    # Use binary search to find the Douglas-Peucker tolerance that gives exactly 3 vertices
    # Start with a range of tolerances
    min_tolerance = 0.0
    max_tolerance = concave_hull_proj.length * 2  # Use 2x perimeter as upper bound

    tolerance = 1.0  # Initial guess
    simplified = None
    best_simplified = None
    best_vertex_count = float("inf")
    max_iterations = 200

    for iteration in range(max_iterations):
        # Simplify the polygon
        test_simplified = concave_hull_proj.simplify(tolerance, preserve_topology=False)

        # Check if it's a polygon and count vertices
        if isinstance(test_simplified, Polygon):
            num_vertices = (
                len(test_simplified.exterior.coords) - 1
            )  # Exclude duplicate last point
        else:
            # If simplification resulted in non-polygon, tolerance is too high
            max_tolerance = tolerance
            tolerance = (min_tolerance + max_tolerance) / 2
            continue

        # Track the best result (closest to 3 vertices)
        if abs(num_vertices - 3) < abs(best_vertex_count - 3):
            best_simplified = test_simplified
            best_vertex_count = num_vertices

        if num_vertices == 3:
            # Found it!
            simplified = test_simplified
            break
        elif num_vertices > 3:
            # Need more simplification (higher tolerance)
            min_tolerance = tolerance
            tolerance = (min_tolerance + max_tolerance) / 2
        else:  # num_vertices < 3
            # Too much simplification (lower tolerance)
            max_tolerance = tolerance
            tolerance = (min_tolerance + max_tolerance) / 2

        # Check if we've converged
        if max_tolerance - min_tolerance < 0.00001:
            # Can't achieve exactly 3 vertices, use best approximation
            simplified = best_simplified
            break

    # If still no result, use best approximation
    if simplified is None:
        simplified = best_simplified

    if simplified is None or not isinstance(simplified, Polygon):
        # Couldn't simplify to triangle
        properties["ta_triangle_vertices"] = None
        properties["ta_triangle_area_sqm"] = None
        properties["ta_triangle_perimeter_m"] = None
        properties["ta_triangle_area_ratio"] = None
        properties["ta_triangularity"] = None
        properties["ta_dp_tolerance"] = None
        properties["ta_triangle_edge_lengths"] = None
        properties["ta_triangle_num_vertices"] = None
        properties["ta_triangle_regularity"] = None
        continue

    # Store the tolerance used
    properties["ta_dp_tolerance"] = tolerance

    # Get triangle vertices in UTM
    triangle_coords_utm = list(simplified.exterior.coords)[
        :-1
    ]  # Remove duplicate last point

    # Transform vertices back to WGS84 for storage
    transformer_inv = pyproj.Transformer.from_crs(
        "EPSG:32618", "EPSG:4326", always_xy=True
    )
    triangle_coords_wgs84 = [
        list(transformer_inv.transform(x, y)) for x, y in triangle_coords_utm
    ]
    properties["ta_triangle_vertices"] = triangle_coords_wgs84

    # Calculate triangle area and perimeter
    triangle_area = simplified.area
    triangle_perimeter = simplified.length

    properties["ta_triangle_area_sqm"] = triangle_area
    properties["ta_triangle_perimeter_m"] = triangle_perimeter

    # Area ratio: ratio of concave hull area to triangle area
    ch_area = concave_hull_proj.area
    if triangle_area > 0:
        area_ratio = ch_area / triangle_area
        properties["ta_triangle_area_ratio"] = area_ratio

        # Normalized triangularity score (0-1, where 1 is most triangular)
        # If ratio is 0-1, keep as is; if > 1, take inverse
        if area_ratio <= 1:
            triangularity = area_ratio
        else:
            triangularity = 1 / area_ratio
        properties["ta_triangularity"] = triangularity
    else:
        properties["ta_triangle_area_ratio"] = None
        properties["ta_triangularity"] = None

    # Calculate edge lengths
    num_triangle_vertices = len(triangle_coords_utm)
    if num_triangle_vertices >= 3:
        edge_lengths = []
        for i in range(num_triangle_vertices):
            p1 = triangle_coords_utm[i]
            p2 = triangle_coords_utm[(i + 1) % num_triangle_vertices]
            length = math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)
            edge_lengths.append(length)

        properties["ta_triangle_edge_lengths"] = edge_lengths
        properties["ta_triangle_num_vertices"] = num_triangle_vertices

        # Triangle regularity: ratio of shortest to longest edge
        # Closer to 1 means more regular (equilateral = 1 for triangles)
        if max(edge_lengths) > 0:
            triangle_regularity = min(edge_lengths) / max(edge_lengths)
            properties["ta_triangle_regularity"] = triangle_regularity
        else:
            properties["ta_triangle_regularity"] = None
    else:
        properties["ta_triangle_edge_lengths"] = None
        properties["ta_triangle_num_vertices"] = (
            num_triangle_vertices if triangle_coords_utm else None
        )
        properties["ta_triangle_regularity"] = None

print(f"  Added triangularity analysis fields (ta_ prefix):")
print(f"    - ta_triangle_vertices: Vertices of simplified triangle (WGS84)")
print(f"    - ta_triangle_num_vertices: Number of vertices in simplified polygon")
print(f"    - ta_triangle_area_sqm: Area of triangle in square meters")
print(f"    - ta_triangle_perimeter_m: Perimeter of triangle in meters")
print(f"    - ta_triangle_area_ratio: Ratio of concave hull area to triangle area")
print(f"    - ta_triangularity: Normalized triangularity score (0-1, 1=triangular)")
print(f"    - ta_dp_tolerance: Douglas-Peucker tolerance used for simplification")
print(f"    - ta_triangle_edge_lengths: Lengths of the triangle edges (m)")
print(f"    - ta_triangle_regularity: Ratio of shortest to longest edge")

# Save the augmented data
print("\nSaving analysis results...")
with open(OUTPUT_DATA_FILE, "w") as f:
    json.dump(data, f)

print(f"Saved to: {OUTPUT_DATA_FILE}")
print("\nDone!")
