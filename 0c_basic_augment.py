"""
NYC Parks Data Augmentation
Add geometric calculations and analysis fields to the filtered parks dataset
"""

import geopandas as gpd
import pyproj
from shapely.ops import transform
from shapely.geometry import mapping

print("Loading NYC Parks GeoJSON...")
SOURCE_DATA_FILE = "./output_data/0b_parks_filtered.geojson"
OUTPUT_DATA_FILE = "./output_data/0c_parks_filtered_augmented.geojson"

# Load the filtered parks data
gdf = gpd.read_file(SOURCE_DATA_FILE)
print(f"Loaded {len(gdf)} parks")

# Reproject to EPSG:32618 (UTM Zone 18N) for accurate measurements in meters
print("Reprojecting to EPSG:32618 (UTM Zone 18N) for accurate measurements...")
gdf_proj = gdf.to_crs(epsg=32618)

print("Calculating geometric properties...")

# Core geometric measurements
gdf["area_sqm"] = gdf_proj.geometry.area
gdf["perimeter_m"] = gdf_proj.geometry.length
gdf["num_vertices"] = gdf.geometry.apply(
    lambda geom: (
        len(geom.exterior.coords)
        if geom.geom_type == "Polygon"
        else (
            sum(len(p.exterior.coords) for p in geom.geoms)
            if geom.geom_type == "MultiPolygon"
            else 0
        )
    )
)
gdf["num_polygons"] = gdf.geometry.apply(
    lambda geom: (
        1
        if geom.geom_type == "Polygon"
        else len(geom.geoms) if geom.geom_type == "MultiPolygon" else 0
    )
)

# Centroid information
centroid = gdf.geometry.centroid
gdf["centroid_lon"] = centroid.x
gdf["centroid_lat"] = centroid.y

# Bounding box dimensions and shape characteristics
gdf["bbox_width"] = gdf_proj.geometry.apply(lambda g: g.bounds[2] - g.bounds[0])
gdf["bbox_height"] = gdf_proj.geometry.apply(lambda g: g.bounds[3] - g.bounds[1])
gdf["aspect_ratio"] = gdf["bbox_width"] / gdf["bbox_height"]

# Convex hull analysis
print("Calculating convex hulls...")
gdf["convex_hull_area"] = gdf_proj.geometry.convex_hull.area
gdf["convexity_ratio"] = gdf["area_sqm"] / gdf["convex_hull_area"]
# Store convex hull geometry as GeoJSON dict (using original WGS84 coordinates)
gdf["convex_hull_polygon"] = gdf.geometry.convex_hull.apply(lambda geom: mapping(geom))


# Multi-polygon analysis - individual polygon areas
def get_polygon_areas_sorted(geom, projected_geom):
    """Extract areas of individual polygons in descending order."""
    if geom.geom_type == "Polygon":
        # Single polygon - return list with one area
        return [projected_geom.area]
    elif geom.geom_type == "MultiPolygon":
        # Multiple polygons - calculate area for each and sort descending
        # Create transformer for this geometry
        transformer = pyproj.Transformer.from_crs(
            "EPSG:4326", "EPSG:32618", always_xy=True
        )

        # Get areas of all polygons
        areas = []
        for poly in geom.geoms:
            # Transform to projected CRS for accurate area
            poly_proj = transform(transformer.transform, poly)
            areas.append(poly_proj.area)

        # Sort in descending order
        return sorted(areas, reverse=True)
    else:
        return []


print("Calculating individual polygon areas...")
gdf["polygon_areas_desc"] = gdf.apply(
    lambda row: get_polygon_areas_sorted(
        row.geometry, gdf_proj.loc[row.name, "geometry"]
    ),
    axis=1,
)

# Polygon area statistics
gdf["largest_polygon_area"] = gdf["polygon_areas_desc"].apply(
    lambda x: x[0] if len(x) > 0 else 0
)
gdf["smallest_polygon_area"] = gdf["polygon_areas_desc"].apply(
    lambda x: x[-1] if len(x) > 0 else 0
)
gdf["polygon_area_ratio"] = gdf.apply(
    lambda row: (
        row["largest_polygon_area"] / row["smallest_polygon_area"]
        if row["smallest_polygon_area"] > 0
        else float("inf")
    ),
    axis=1,
)

print("Saving augmented data...")
gdf.to_file(OUTPUT_DATA_FILE, driver="GeoJSON")
print(f"Saved to: {OUTPUT_DATA_FILE}")

print("\nAdded the following fields:")
print("  - area_sqm: Area in square meters")
print("  - perimeter_m: Perimeter in meters")
print("  - num_vertices: Number of vertices in the geometry")
print("  - num_polygons: Number of separate polygons")
print("  - centroid_lon: Centroid longitude")
print("  - centroid_lat: Centroid latitude")
print("  - bbox_width: Bounding box width in meters")
print("  - bbox_height: Bounding box height in meters")
print("  - aspect_ratio: Width/height ratio")
print("  - convex_hull_area: Area of the convex hull in square meters")
print("  - convexity_ratio: Ratio of actual area to convex hull area")
print("  - convex_hull_polygon: Convex hull geometry as GeoJSON polygon")
print("  - polygon_areas_desc: List of individual polygon areas (descending)")
print("  - largest_polygon_area: Area of the largest polygon")
print("  - smallest_polygon_area: Area of the smallest polygon")
print("  - polygon_area_ratio: Ratio of largest to smallest polygon")
print("\nDone!")
