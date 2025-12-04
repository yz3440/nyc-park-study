"""
NYC Parks Concave Hull Analysis
Analyze geometric properties of the concave hulls for NYC parks
"""

import json
import math
import geopandas as gpd
import numpy as np
from shapely import geometry
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
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
        # MRR always contains the shape, so ratio is always <= 1
        properties["ra_rectangularity"] = area_ratio
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
        properties["ta_triangle_ch_area_ratio"] = None
        properties["ta_triangle_ch_intersection_area"] = None
        properties["ta_triangle_ch_intersection_area_ratio"] = None
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

    # Incremental simplification approach:
    # Start with original polygon and small epsilon, incrementally simplify
    # using each result as input for the next iteration
    perimeter = concave_hull_proj.length

    # Initial epsilon and increment proportional to perimeter
    epsilon = perimeter * 0.001  # Start with 0.1% of perimeter
    increment = perimeter * 0.001  # Initial increment

    # Handle MultiPolygon by extracting largest polygon
    if isinstance(concave_hull_proj, Polygon):
        current_polygon = concave_hull_proj
    else:
        # MultiPolygon - extract the largest polygon by area
        polygons = [g for g in concave_hull_proj.geoms if isinstance(g, Polygon)]
        if polygons:
            current_polygon = max(polygons, key=lambda p: p.area)
        else:
            current_polygon = None

    simplified = None
    best_simplified = current_polygon
    best_vertex_count = (
        len(current_polygon.exterior.coords) - 1 if current_polygon else float("inf")
    )
    max_iterations = 400
    final_iteration = 0
    tolerance = epsilon  # Track cumulative tolerance for reporting

    if current_polygon is not None:
        num_vertices = len(current_polygon.exterior.coords) - 1

        for iteration in range(max_iterations):
            final_iteration = iteration

            if num_vertices == 3:
                # Found it!
                simplified = current_polygon
                break

            if num_vertices < 3:
                # Can't simplify further
                break

            # Simplify the current polygon (not the original!)
            test_simplified = current_polygon.simplify(epsilon, preserve_topology=False)

            # Handle result based on geometry type
            if isinstance(test_simplified, Polygon) and not test_simplified.is_empty:
                # Good - still a single polygon
                result_polygon = test_simplified
            elif isinstance(test_simplified, MultiPolygon):
                # Polygon split into multiple parts - extract the largest one and continue
                parts = [
                    g
                    for g in test_simplified.geoms
                    if isinstance(g, Polygon) and not g.is_empty
                ]
                if parts:
                    result_polygon = max(parts, key=lambda p: p.area)
                else:
                    # No valid parts, reduce epsilon and try again
                    epsilon -= increment
                    increment *= 0.5
                    epsilon += increment
                    if increment < 0.0001:
                        break
                    continue
            else:
                # Invalid result (empty, LineString, etc.), reduce epsilon
                epsilon -= increment
                increment *= 0.5
                epsilon += increment
                if increment < 0.0001:
                    break
                continue

            new_num_vertices = len(result_polygon.exterior.coords) - 1

            if new_num_vertices >= 3:
                # Good simplification, use this result for next iteration
                current_polygon = result_polygon
                num_vertices = new_num_vertices
                tolerance += epsilon
                epsilon += increment

                # Track best result
                if abs(num_vertices - 3) < abs(best_vertex_count - 3):
                    best_simplified = current_polygon
                    best_vertex_count = num_vertices
            else:
                # Overshot (< 3 vertices), back off
                epsilon -= increment
                increment *= 0.5
                epsilon += increment

                if increment < 0.0001:
                    # Converged, can't achieve exactly 3 vertices
                    break

    # Use best result if we didn't find exactly 3
    if simplified is None:
        simplified = best_simplified

    # Handle 4-vertex case: try all 4 possible triangles and pick the best one
    if simplified is not None and isinstance(simplified, Polygon):
        quad_coords = list(simplified.exterior.coords)[:-1]  # Remove duplicate last
        if len(quad_coords) == 4:
            quad_area = simplified.area
            best_triangle = None
            best_ratio = 0.0  # Looking for ratio closest to 1

            # Try removing each of the 4 vertices
            for i in range(4):
                # Create triangle by skipping vertex i
                tri_coords = [quad_coords[j] for j in range(4) if j != i]
                tri_coords.append(tri_coords[0])  # Close the polygon
                triangle = Polygon(tri_coords)

                if triangle.is_valid and not triangle.is_empty:
                    tri_area = triangle.area
                    # Calculate ratio (normalize to <= 1)
                    if quad_area > 0:
                        ratio = tri_area / quad_area
                        if ratio > 1:
                            ratio = 1 / ratio

                        if ratio > best_ratio:
                            best_ratio = ratio
                            best_triangle = triangle

            if best_triangle is not None:
                simplified = best_triangle

    if simplified is None or not isinstance(simplified, Polygon):
        # Couldn't simplify to triangle
        properties["ta_triangle_vertices"] = None
        properties["ta_triangle_area_sqm"] = None
        properties["ta_triangle_perimeter_m"] = None
        properties["ta_triangle_ch_area_ratio"] = None
        properties["ta_triangle_ch_intersection_area"] = None
        properties["ta_triangle_ch_intersection_area_ratio"] = None
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

    # Calculate concave hull area ratio (ch area / triangle area)
    ch_area = concave_hull_proj.area
    if triangle_area > 0:
        ch_area_ratio = ch_area / triangle_area
        properties["ta_triangle_ch_area_ratio"] = ch_area_ratio
        # Normalize to <= 1 by taking inverse if > 1
        ch_area_ratio_normalized = (
            ch_area_ratio if ch_area_ratio <= 1 else 1 / ch_area_ratio
        )
    else:
        properties["ta_triangle_ch_area_ratio"] = None
        ch_area_ratio_normalized = None

    # Calculate intersection of concave hull and triangle
    intersection = concave_hull_proj.intersection(simplified)
    # Sum areas if intersection is a collection of geometries
    if intersection.is_empty:
        intersect_area = 0
    elif hasattr(intersection, "geoms"):
        intersect_area = sum(g.area for g in intersection.geoms)
    else:
        intersect_area = intersection.area
    properties["ta_triangle_ch_intersection_area"] = intersect_area

    # Leftout area ratio (leftout area / triangle area)
    leftout_area = (
        ch_area - intersect_area
    )  # leftout area is the area of the concave hull that is not covered by the triangle
    if triangle_area > 0:
        leftout_area_ratio = leftout_area / triangle_area
        properties["ta_triangle_leftout_area_ratio"] = leftout_area_ratio
    else:
        properties["ta_triangle_leftout_area_ratio"] = None

    # Intersection area ratio (intersection area / triangle area)
    if triangle_area > 0:
        intersection_area_ratio = intersect_area / triangle_area
        properties["ta_triangle_ch_intersection_area_ratio"] = intersection_area_ratio

    else:
        properties["ta_triangle_ch_intersection_area_ratio"] = None
        intersection_ratio_normalized = None

    # MARK: Triangularity is the product of both normalized ratios
    if (
        ch_area_ratio_normalized is not None
        and intersection_ratio_normalized is not None
    ):
        triangularity = (
            ch_area_ratio_normalized
            * intersection_area_ratio
            * (1 - leftout_area_ratio)
        )
        properties["ta_triangularity"] = triangularity
    else:
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
print(f"    - ta_triangle_ch_area_ratio: Ratio of concave hull area to triangle area")
print(
    f"    - ta_triangle_ch_intersection_area: Area of intersection (concave hull ∩ triangle)"
)
print(
    f"    - ta_triangle_ch_intersection_area_ratio: Ratio of intersection area to triangle area"
)
print(f"    - ta_triangularity: Product of normalized area ratios (0-1, 1=triangular)")
print(f"    - ta_dp_tolerance: Douglas-Peucker tolerance used for simplification")
print(f"    - ta_triangle_edge_lengths: Lengths of the triangle edges (m)")
print(f"    - ta_triangle_regularity: Ratio of shortest to longest edge")

# Save the augmented data
print("\nSaving analysis results...")
with open(OUTPUT_DATA_FILE, "w") as f:
    json.dump(data, f)

print(f"Saved to: {OUTPUT_DATA_FILE}")

# MARK: Generate Triangle Geometry GeoJSON

print("\nGenerating triangle geometry GeoJSON...")

# Create a new GeoJSON with triangle geometries
triangle_data = {"type": "FeatureCollection", "features": []}

for feature in data["features"]:
    properties = feature["properties"]

    # Get the triangle vertices
    triangle_vertices = properties.get("ta_triangle_vertices")

    if triangle_vertices and len(triangle_vertices) >= 3:
        # Create a new feature with the triangle as the geometry
        triangle_feature = {
            "type": "Feature",
            "properties": properties.copy(),  # Copy all properties
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    triangle_vertices + [triangle_vertices[0]]  # Close the polygon
                ],
            },
        }
        triangle_data["features"].append(triangle_feature)
    else:
        # Include features without triangles but with null geometry
        null_feature = {
            "type": "Feature",
            "properties": properties.copy(),
            "geometry": None,
        }
        triangle_data["features"].append(null_feature)

# Save the triangle geometry GeoJSON
TRIANGLE_OUTPUT_FILE = "./output_data/2a_parks_triangles_geometry.geojson"
with open(TRIANGLE_OUTPUT_FILE, "w") as f:
    json.dump(triangle_data, f)

print(f"Saved triangle geometries to: {TRIANGLE_OUTPUT_FILE}")
print(f"  Total features: {len(triangle_data['features'])}")
print(
    f"  Features with triangles: {sum(1 for f in triangle_data['features'] if f['geometry'] is not None)}"
)

print("\nDone!")
