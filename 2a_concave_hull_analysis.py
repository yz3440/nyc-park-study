"""
NYC Parks Concave Hull Analysis
Analyze geometric properties of the concave hulls for NYC parks
"""

import json
import math
from shapely.geometry import shape, Polygon, MultiPolygon, Point, LineString
from shapely.ops import transform
from shapely.validation import make_valid
import pyproj
import numpy as np


def resample_polyline(
    coords: list[tuple[float, float]], num_points: int
) -> list[tuple[float, float]]:
    """
    Resample a polyline to a fixed number of evenly-spaced points.

    Args:
        coords: List of (x, y) coordinates forming the polyline
        num_points: Number of points to resample to

    Returns:
        List of resampled (x, y) coordinates
    """
    if len(coords) < 2:
        return coords

    if num_points < 2:
        return [coords[0]]

    # Calculate cumulative distances along the polyline
    coords_arr = np.array(coords)
    diffs = np.diff(coords_arr, axis=0)
    segment_lengths = np.sqrt((diffs**2).sum(axis=1))
    cumulative_lengths = np.concatenate([[0], np.cumsum(segment_lengths)])
    total_length = cumulative_lengths[-1]

    if total_length == 0:
        return [coords[0]] * num_points

    # Generate evenly spaced target distances
    target_distances = np.linspace(0, total_length, num_points)

    # Interpolate points at target distances
    resampled = []
    for target in target_distances:
        # Find which segment contains this distance
        idx = np.searchsorted(cumulative_lengths, target, side="right") - 1
        idx = max(0, min(idx, len(coords) - 2))

        # Interpolate within the segment
        seg_start_dist = cumulative_lengths[idx]
        seg_length = segment_lengths[idx] if idx < len(segment_lengths) else 0

        if seg_length == 0:
            resampled.append(coords[idx])
        else:
            t = (target - seg_start_dist) / seg_length
            t = max(0, min(1, t))
            x = coords[idx][0] + t * (coords[idx + 1][0] - coords[idx][0])
            y = coords[idx][1] + t * (coords[idx + 1][1] - coords[idx][1])
            resampled.append((x, y))

    return resampled


def calculate_edge_deviation_squared_error(
    concave_hull_proj: Polygon | MultiPolygon, triangle_proj: Polygon
) -> float | None:
    """
    Calculate the edge deviation error between a concave hull and its simplified triangle.

    This measures how much the concave hull edges deviate from the triangle edges.
    For each triangle edge, we find the corresponding concave hull vertices and measure
    their perpendicular distances to the triangle edge line.

    Algorithm:
    1. Shift concave hull vertices so the first vertex aligns with the first triangle vertex
    2. Split concave hull vertices into three segments, one for each triangle edge
    3. Resample each segment to a fixed number of points (200) for fair comparison
    4. For each segment, calculate the mean perpendicular distance from resampled points to the edge
    5. Normalize by sqrt(triangle area) for scale-independence
    6. Return the sum of the three normalized errors

    Args:
        concave_hull_proj: The concave hull polygon in projected coordinates (UTM)
        triangle_proj: The simplified triangle polygon in projected coordinates (UTM)

    Returns:
        The total edge deviation error (sum of three normalized mean errors), or None if invalid
    """
    # Handle MultiPolygon by extracting the largest polygon
    if isinstance(concave_hull_proj, MultiPolygon):
        polygons = [g for g in concave_hull_proj.geoms if isinstance(g, Polygon)]
        if polygons:
            concave_hull_proj = max(polygons, key=lambda p: p.area)
        else:
            return None

    if not isinstance(concave_hull_proj, Polygon) or not isinstance(
        triangle_proj, Polygon
    ):
        return None

    # Get vertices (remove duplicate last point)
    ch_coords = list(concave_hull_proj.exterior.coords)[:-1]
    tri_coords = list(triangle_proj.exterior.coords)[:-1]

    if len(ch_coords) < 3 or len(tri_coords) != 3:
        return None

    # Step 1: Find the concave hull vertex closest to each triangle vertex
    # This gives us the split points for the three segments
    split_indices = []
    for tri_vertex in tri_coords:
        min_dist = float("inf")
        best_idx = 0
        for i, ch_pt in enumerate(ch_coords):
            dist = math.sqrt(
                (ch_pt[0] - tri_vertex[0]) ** 2 + (ch_pt[1] - tri_vertex[1]) ** 2
            )
            if dist < min_dist:
                min_dist = dist
                best_idx = i
        split_indices.append(best_idx)

    # Shift CH coordinates so the first split index becomes 0
    start_idx = split_indices[0]
    ch_coords_shifted = ch_coords[start_idx:] + ch_coords[:start_idx]

    # Adjust split indices relative to the shifted array
    n = len(ch_coords)
    split_indices_shifted = [(idx - start_idx) % n for idx in split_indices]

    # Use sqrt of triangle area for normalization (gives characteristic length scale)
    triangle_area = triangle_proj.area
    if triangle_area <= 0:
        return None
    normalization_length = math.sqrt(triangle_area)

    total_squared_error = 0.0

    for edge_idx in range(3):
        # Triangle edge goes from tri_coords[edge_idx] to tri_coords[(edge_idx + 1) % 3]
        edge_start = tri_coords[edge_idx]
        edge_end = tri_coords[(edge_idx + 1) % 3]

        # Edge vector
        dx = edge_end[0] - edge_start[0]
        dy = edge_end[1] - edge_start[1]
        edge_length = math.sqrt(dx * dx + dy * dy)

        if edge_length == 0:
            continue

        # Get the CH vertices for this segment (from split[edge_idx] to split[(edge_idx+1)%3])
        seg_start = split_indices_shifted[edge_idx]
        seg_end = split_indices_shifted[(edge_idx + 1) % 3]

        # Build segment vertices (inclusive of both endpoints, wrapping if needed)
        if seg_end > seg_start:
            # Normal case: segment doesn't wrap
            segment_vertices = ch_coords_shifted[seg_start : seg_end + 1]
        elif seg_end < seg_start:
            # Wrapping case: segment goes from seg_start to end, then from 0 to seg_end
            segment_vertices = (
                ch_coords_shifted[seg_start:] + ch_coords_shifted[: seg_end + 1]
            )
        else:
            # seg_start == seg_end: just one vertex
            segment_vertices = [ch_coords_shifted[seg_start]]

        if len(segment_vertices) < 2:
            # If only one vertex (the corner itself), no edge deviation to measure
            continue

        # Resample segment to fixed number of points to avoid bias from oversampled polygons
        RESAMPLE_COUNT = 400
        segment_vertices = resample_polyline(segment_vertices, RESAMPLE_COUNT)

        # Calculate perpendicular distances from each resampled point to the triangle edge line
        # Distance from point (px, py) to line through (x1, y1) and (x2, y2):
        # d = |cross_product| / edge_length = |(x2-x1)(y1-py) - (x1-px)(y2-y1)| / edge_length
        squared_distances = []
        for vx, vy in segment_vertices:
            # Perpendicular distance to the infinite line
            cross = abs(dx * (edge_start[1] - vy) - (edge_start[0] - vx) * dy)
            dist = cross / edge_length
            normalized_dist = dist / normalization_length
            squared_distances.append(normalized_dist * normalized_dist)

        # Mean distance normalized by sqrt(triangle area)
        mean_dist_squared = sum(squared_distances) / len(squared_distances)

        total_squared_error += mean_dist_squared

    return total_squared_error


def calculate_edge_area_deviation(
    concave_hull_proj: Polygon | MultiPolygon, triangle_proj: Polygon
) -> float | None:
    """
    Calculate the area deviation between concave hull edges and triangle edges.

    For each triangle edge, measures the total area between the concave hull
    boundary and the straight triangle edge. Areas on both sides of the edge
    (where CH bulges outward or inward relative to the triangle) are counted
    as deviation by taking absolute values.

    Algorithm:
    1. Find CH vertices closest to each triangle vertex (split points)
    2. For each triangle edge A→B, get the corresponding CH segment
    3. Build a polygon from: A → CH segment vertices → B → A
    4. If the polygon self-intersects (CH crosses the edge), use make_valid
       to split it and sum absolute areas of all parts
    5. Normalize total area by triangle area for scale-independence

    Args:
        concave_hull_proj: The concave hull polygon in projected coordinates (UTM)
        triangle_proj: The simplified triangle polygon in projected coordinates (UTM)

    Returns:
        The normalized area deviation (sum of edge areas / triangle area), or None if invalid
    """
    # Handle MultiPolygon by extracting the largest polygon
    if isinstance(concave_hull_proj, MultiPolygon):
        polygons = [g for g in concave_hull_proj.geoms if isinstance(g, Polygon)]
        if polygons:
            concave_hull_proj = max(polygons, key=lambda p: p.area)
        else:
            return None

    if not isinstance(concave_hull_proj, Polygon) or not isinstance(
        triangle_proj, Polygon
    ):
        return None

    # Get vertices (remove duplicate last point)
    ch_coords = list(concave_hull_proj.exterior.coords)[:-1]
    tri_coords = list(triangle_proj.exterior.coords)[:-1]

    if len(ch_coords) < 3 or len(tri_coords) != 3:
        return None

    # Find CH vertex closest to each triangle vertex
    split_indices = []
    for tri_vertex in tri_coords:
        min_dist = float("inf")
        best_idx = 0
        for i, ch_pt in enumerate(ch_coords):
            dist = math.sqrt(
                (ch_pt[0] - tri_vertex[0]) ** 2 + (ch_pt[1] - tri_vertex[1]) ** 2
            )
            if dist < min_dist:
                min_dist = dist
                best_idx = i
        split_indices.append(best_idx)

    # Shift CH coordinates so first split index is 0
    start_idx = split_indices[0]
    ch_coords_shifted = ch_coords[start_idx:] + ch_coords[:start_idx]
    n = len(ch_coords)
    split_indices_shifted = [(idx - start_idx) % n for idx in split_indices]

    triangle_area = triangle_proj.area
    if triangle_area <= 0:
        return None

    total_deviation_area = 0.0

    for edge_idx in range(3):
        # Triangle edge endpoints
        A = tri_coords[edge_idx]
        B = tri_coords[(edge_idx + 1) % 3]

        # Get CH segment indices
        seg_start = split_indices_shifted[edge_idx]
        seg_end = split_indices_shifted[(edge_idx + 1) % 3]

        # Build segment vertices
        if seg_end > seg_start:
            segment_vertices = ch_coords_shifted[seg_start : seg_end + 1]
        elif seg_end < seg_start:
            segment_vertices = (
                ch_coords_shifted[seg_start:] + ch_coords_shifted[: seg_end + 1]
            )
        else:
            segment_vertices = [ch_coords_shifted[seg_start]]

        if len(segment_vertices) < 2:
            # Only one corner vertex - measure triangle A-corner-B
            corner = segment_vertices[0]
            tri_area = 0.5 * abs(
                (corner[0] - A[0]) * (B[1] - A[1]) - (B[0] - A[0]) * (corner[1] - A[1])
            )
            total_deviation_area += tri_area
            continue

        # Build polygon from: A → CH segment → B → back to A
        # This polygon captures the area between the CH boundary and the triangle edge
        poly_coords = [A] + list(segment_vertices) + [B]
        try:
            deviation_poly = Polygon(poly_coords)

            if deviation_poly.is_valid and not deviation_poly.is_empty:
                total_deviation_area += deviation_poly.area
            else:
                # Handle invalid (self-intersecting) polygon
                # This happens when CH crosses the triangle edge
                valid_geom = make_valid(deviation_poly)
                if hasattr(valid_geom, "geoms"):
                    for g in valid_geom.geoms:
                        if hasattr(g, "area"):
                            total_deviation_area += abs(g.area)
                elif hasattr(valid_geom, "area"):
                    total_deviation_area += abs(valid_geom.area)
        except Exception:
            continue

    # Return deviation area normalized by triangle area
    return total_deviation_area / triangle_area


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
        properties["ta_edge_deviation_squared_error"] = None
        properties["ta_edge_deviation_squared_factor"] = None
        properties["ta_edge_area_deviation"] = None
        properties["ta_edge_area_deviation_factor"] = None
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
        properties["ta_edge_deviation_squared_error"] = None
        properties["ta_edge_deviation_squared_factor"] = None
        properties["ta_edge_area_deviation"] = None
        properties["ta_edge_area_deviation_factor"] = None
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

    original_area = properties.get("area_sqm")
    if original_area is not None and triangle_area > 0:
        original_ratio = original_area / triangle_area
        original_ratio_normalized = (
            original_ratio if original_ratio <= 1 else 1 / original_ratio
        )
        properties["ta_triangle_original_ratio"] = original_ratio
    else:
        properties["ta_triangle_original_ratio"] = None

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

    # Calculate edge deviation squared error
    edge_deviation_squared_error = calculate_edge_deviation_squared_error(
        concave_hull_proj, simplified
    )
    properties["ta_edge_deviation_squared_error"] = edge_deviation_squared_error

    # Calculate edge deviation squared factor (inverse of error, clamped to [0, 1])
    if edge_deviation_squared_error is not None and edge_deviation_squared_error > 0:
        # Use 1 / (1 + error) to map error to (0, 1] range
        # This ensures factor approaches 1 when error is near 0
        # and approaches 0 as error increases
        edge_deviation_squared_factor = 1 / (1 + edge_deviation_squared_error * 10)
    else:
        edge_deviation_squared_factor = (
            1.0 if edge_deviation_squared_error == 0 else None
        )
    properties["ta_edge_deviation_squared_factor"] = edge_deviation_squared_factor

    # Calculate edge area deviation (area between CH edges and triangle edges)
    edge_area_deviation = calculate_edge_area_deviation(concave_hull_proj, simplified)
    properties["ta_edge_area_deviation"] = edge_area_deviation

    # Calculate edge area deviation factor (inverse of deviation, clamped to [0, 1])
    if edge_area_deviation is not None and edge_area_deviation > 0:
        # Use 1 / (1 + deviation) to map deviation to (0, 1] range
        edge_area_deviation_factor = 1 / (1 + edge_area_deviation * 2)
    else:
        edge_area_deviation_factor = 1.0 if edge_area_deviation == 0 else None
    properties["ta_edge_area_deviation_factor"] = edge_area_deviation_factor

    # MARK: Triangularity is the product of both normalized ratios
    # Save individual factors for analysis
    properties["ta_triangularity_factor_original_ratio"] = original_ratio_normalized

    properties["ta_triangularity_factor_ch_area_ratio"] = ch_area_ratio_normalized
    properties["ta_triangularity_factor_ch_intersection_area_ratio"] = (
        intersection_area_ratio
    )
    leftout_factor = (
        max(1 - leftout_area_ratio, 0) if leftout_area_ratio is not None else None
    )
    properties["ta_triangularity_factor_leftout"] = leftout_factor
    properties["ta_triangularity_factor_edge_deviation_squared"] = (
        edge_deviation_squared_factor
    )
    properties["ta_triangularity_factor_edge_area_deviation"] = (
        edge_area_deviation_factor
    )

    if (
        ch_area_ratio_normalized is not None
        and intersection_area_ratio is not None
        and leftout_factor is not None
        and edge_deviation_squared_factor is not None
    ):
        triangularity = (
            min(
                # intersection_area_ratio,
                # leftout_factor,
                original_ratio_normalized,
                ch_area_ratio_normalized,
            )
            * edge_deviation_squared_factor
            * edge_area_deviation_factor**2
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
print(
    f"    - ta_edge_deviation_squared_error: Sum of normalized mean squared edge deviations"
)
print(f"    - ta_edge_deviation_squared_factor: 1/(1+error), penalizes jagged edges")
print(
    f"    - ta_edge_area_deviation: Normalized area between CH edges and triangle edges"
)
print(f"    - ta_edge_area_deviation_factor: 1/(1+deviation), penalizes jagged edges")
print(f"    - ta_triangularity_factor_area_ratio: Area ratio factor")
print(f"    - ta_triangularity_factor_intersection: Intersection factor")
print(f"    - ta_triangularity_factor_leftout: Leftout area factor (1 - leftout_ratio)")
print(
    f"    - ta_triangularity_factor_edge_deviation_squared: Edge deviation squared factor"
)
print(f"    - ta_triangularity_factor_edge_area_deviation: Edge area deviation factor")
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
