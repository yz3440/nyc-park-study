"""
Compute concave hulls for NYC park MultiPolygon features.

Reads 0c_parks_filtered_augmented.geojson and produces:
  - 1a_parks_concave_hulls.geojson       (geometries replaced with hulls)
  - 1a_parks_with_concave_hulls.geojson   (original geom + concave_hull_polygon property)

Uses GEOS ConcaveHullOfPolygons via ctypes (no C++ build needed).
Requires shapely >= 2.0 (which bundles GEOS >= 3.11).
"""

import ctypes
import ctypes.util
import json
import os
from ctypes import c_char_p, c_double, c_uint, c_void_p
from pathlib import Path

from shapely import from_wkt, to_wkt
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.validation import make_valid

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SOURCE_DATA_FILE = "./output_data/0c_parks_filtered_augmented.geojson"
OUTPUT_PATH_HULLS = "./output_data/1a_parks_concave_hulls.geojson"
OUTPUT_PATH_WITH_HULLS = "./output_data/1a_parks_with_concave_hulls.geojson"

# ---------------------------------------------------------------------------
# Whitelist (empty = process all features)
# ---------------------------------------------------------------------------

EAPPLY_WHITELIST: set[str] = {
    # "Van Voorhees Playground",
    # "Grand Army Plaza",
    # "Prospect Park",
    # "Red Hook Recreation Area",
    # "Broadway Malls 59th-110th",
}

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

START_RATIO = 0.01
RATIO_INCREMENT = 0.01
MAX_ATTEMPTS = 100

METERS_PER_DEGREE = 111319.9
SQ_METERS_PER_SQ_DEGREE = METERS_PER_DEGREE * METERS_PER_DEGREE
TINY_POLYGON_AREA_THRESHOLD_SQ_METERS = 500.0
TINY_POLYGON_AREA_THRESHOLD = TINY_POLYGON_AREA_THRESHOLD_SQ_METERS / SQ_METERS_PER_SQ_DEGREE

# ---------------------------------------------------------------------------
# GEOS C API setup (from manhattan-blocks-data/concave_hull.py)
# ---------------------------------------------------------------------------

def _load_geos():
    import glob
    import shapely as _shapely

    paths = []
    shapely_dir = os.path.dirname(_shapely.__file__)
    paths += sorted(glob.glob(os.path.join(shapely_dir, ".dylibs", "libgeos_c*.dylib")))
    paths += sorted(glob.glob(os.path.join(shapely_dir, ".libs", "libgeos_c*.so*")))
    paths += [
        "/opt/homebrew/lib/libgeos_c.dylib",
        "/usr/local/lib/libgeos_c.dylib",
        "/usr/lib/libgeos_c.so",
    ]
    found = ctypes.util.find_library("geos_c")
    if found:
        paths.append(found)

    for path in paths:
        try:
            lib = ctypes.CDLL(path)
            _ = lib.GEOSConcaveHullOfPolygons
            return lib
        except (OSError, AttributeError):
            continue

    raise RuntimeError(
        "Could not find libgeos_c with GEOSConcaveHullOfPolygons. "
        "Requires shapely >= 2.0 (GEOS >= 3.11)."
    )


def _setup_geos(lib):
    lib.initGEOS.argtypes = [c_void_p, c_void_p]
    lib.initGEOS.restype = None
    lib.finishGEOS.argtypes = []
    lib.finishGEOS.restype = None
    lib.GEOSGeomFromWKT.restype = c_void_p
    lib.GEOSGeomFromWKT.argtypes = [c_char_p]
    lib.GEOSGeomToWKT.restype = c_char_p
    lib.GEOSGeomToWKT.argtypes = [c_void_p]
    lib.GEOSConcaveHullOfPolygons.restype = c_void_p
    lib.GEOSConcaveHullOfPolygons.argtypes = [c_void_p, c_double, c_uint, c_uint]
    lib.GEOSGeom_destroy.argtypes = [c_void_p]
    lib.GEOSGeom_destroy.restype = None
    lib.initGEOS(None, None)
    return lib


_geos = _setup_geos(_load_geos())


def _shapely_to_geos(geometry):
    wkt = to_wkt(geometry).encode("ascii")
    ptr = _geos.GEOSGeomFromWKT(wkt)
    if not ptr:
        raise ValueError(f"Failed to parse geometry WKT: {to_wkt(geometry)[:100]}...")
    return ptr


def _geos_to_shapely(ptr):
    wkt = _geos.GEOSGeomToWKT(ptr)
    if not wkt:
        raise ValueError("Failed to convert GEOS geometry to WKT")
    return from_wkt(wkt.decode("ascii"))


def _is_single(geom):
    """Check if a Shapely geometry is effectively a single polygon."""
    if geom.geom_type == "Polygon":
        return True
    if geom.geom_type == "MultiPolygon":
        return len(geom.geoms) == 1
    return False


# ---------------------------------------------------------------------------
# Core: adaptive concave hull per geometry
# ---------------------------------------------------------------------------

def _concave_hull_of_polygons(geometry, length_ratio, is_tight=True, is_holes_allowed=False):
    """Single call to GEOS ConcaveHullOfPolygons. Returns Shapely geometry or None."""
    geom_ptr = _shapely_to_geos(geometry)
    try:
        hull_ptr = _geos.GEOSConcaveHullOfPolygons(
            geom_ptr, c_double(length_ratio),
            c_uint(1 if is_tight else 0),
            c_uint(1 if is_holes_allowed else 0),
        )
        if not hull_ptr:
            return None
        result = _geos_to_shapely(hull_ptr)
        _geos.GEOSGeom_destroy(hull_ptr)
        return result
    finally:
        _geos.GEOSGeom_destroy(geom_ptr)


def adaptive_concave_hull(geometry, start_ratio=START_RATIO, increment=RATIO_INCREMENT,
                          max_attempts=MAX_ATTEMPTS):
    """Increase length_ratio until result is a single polygon. Returns (hull, attempts).

    Always returns a hull. Falls back to convex hull if GEOS ConcaveHullOfPolygons
    returns NULL (which can happen for certain geometry configurations where the
    ratio-based C API differs from the length-based C++ API).
    """
    if not geometry.is_valid:
        geometry = make_valid(geometry)
        if geometry.geom_type == "GeometryCollection":
            polys = [g for g in geometry.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
            mp_parts = []
            for g in polys:
                if g.geom_type == "Polygon":
                    mp_parts.append(g)
                else:
                    mp_parts.extend(g.geoms)
            geometry = MultiPolygon(mp_parts) if mp_parts else geometry

    last_result = None
    ratio = start_ratio
    for attempt in range(max_attempts):
        result = _concave_hull_of_polygons(geometry, ratio)
        if result is None:
            ratio = min(ratio + increment, 1.0)
            continue

        last_result = result
        if _is_single(result):
            return result, attempt

        ratio = min(ratio + increment, 1.0)

    if last_result is not None:
        return last_result, max_attempts

    # GEOS returned NULL at all ratios -- fall back to convex hull
    hull = geometry.convex_hull
    return hull, max_attempts


# ---------------------------------------------------------------------------
# Post-processing: remove tiny polygon fragments
# ---------------------------------------------------------------------------

def remove_tiny_polygons(geom, properties, threshold=TINY_POLYGON_AREA_THRESHOLD):
    """If geom is a 2-part MultiPolygon with one tiny part, drop it. Returns (geom, removed_area_or_None)."""
    if geom.geom_type != "MultiPolygon":
        return geom, None
    parts = list(geom.geoms)
    if len(parts) != 2:
        return geom, None

    area0, area1 = parts[0].area, parts[1].area
    if area0 < area1 and area0 < threshold:
        return parts[1], area0
    if area1 < area0 and area1 < threshold:
        return parts[0], area1
    return geom, None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    print(f"Reading GeoJSON file: {SOURCE_DATA_FILE}")
    with open(SOURCE_DATA_FILE) as f:
        data = json.load(f)

    features = data["features"]
    print(f"Processing {len(features)} features...")

    output_features_hulls = []
    output_features_with_hulls = []
    processed = 0
    skipped = 0

    for feat in features:
        geom = shape(feat["geometry"])
        props = dict(feat.get("properties", {}))
        eapply = props.get("eapply", "")

        # --- Whitelist filtering ---
        if EAPPLY_WHITELIST:
            if eapply not in EAPPLY_WHITELIST:
                output_features_hulls.append(feat)
                output_features_with_hulls.append(feat)
                skipped += 1
                continue

        # --- Non-MultiPolygon: pass through ---
        if geom.geom_type != "MultiPolygon":
            output_features_hulls.append(feat)
            output_features_with_hulls.append(feat)
            processed += 1
            continue

        # --- Compute adaptive concave hull ---
        name = props.get("name311", "(unknown)")
        print(f"Name: {name}")

        hull, attempts = adaptive_concave_hull(geom)

        if hull is None:
            print(f"  WARNING: hull computation failed for {eapply}")
            output_features_hulls.append(feat)
            output_features_with_hulls.append(feat)
            processed += 1
            continue

        if attempts > 0:
            print(f"  ⚡ {eapply} required {attempts + 1} attempts (ratio: {START_RATIO + attempts * RATIO_INCREMENT:.4f})")

        # Feature with hull geometry (for hulls-only output)
        hull_feat = {
            "type": "Feature",
            "properties": props,
            "geometry": mapping(hull),
        }
        if "id" in feat:
            hull_feat["id"] = feat["id"]
        output_features_hulls.append(hull_feat)

        # Feature with original geometry + concave_hull_polygon property
        props_with_hull = dict(props)
        props_with_hull["concave_hull_polygon"] = mapping(hull)
        with_hull_feat = {
            "type": "Feature",
            "properties": props_with_hull,
            "geometry": feat["geometry"],
        }
        if "id" in feat:
            with_hull_feat["id"] = feat["id"]
        output_features_with_hulls.append(with_hull_feat)

        processed += 1
        if processed % 100 == 0:
            print(f"  Processed {processed} features...")

    print(f"Processed {processed} features")
    if skipped > 0:
        print(f"Skipped {skipped} features (not in whitelist)")

    # --- Post-processing: tiny polygon removal + issue reporting ---
    multi_polygon_issues = []
    tiny_removed = 0

    for i, feat in enumerate(output_features_hulls):
        geom = shape(feat["geometry"])
        if geom.geom_type != "MultiPolygon":
            continue
        parts = list(geom.geoms)
        if len(parts) <= 1:
            continue

        eapply_name = feat["properties"].get("eapply", "(no eapply value)")

        cleaned, removed_area = remove_tiny_polygons(geom, feat["properties"])
        if removed_area is not None:
            output_features_hulls[i] = {
                **feat,
                "geometry": mapping(cleaned),
            }
            area_sqm = removed_area * SQ_METERS_PER_SQ_DEGREE
            print(f"  ✓ {eapply_name}: Removed tiny polygon ({int(area_sqm)} sq m)")
            tiny_removed += 1
        else:
            multi_polygon_issues.append((eapply_name, feat))

    if tiny_removed > 0:
        print(f"\n✓ Removed {tiny_removed} tiny polygon(s) from MultiPolygons.")

    if multi_polygon_issues:
        print(f"\n⚠️  WARNING: {len(multi_polygon_issues)} feature(s) still have MultiPolygons with multiple polygons:")
        for name, _ in multi_polygon_issues:
            print(f"  - {name}")
        print("\nConsider adjusting START_RATIO / RATIO_INCREMENT to merge these polygons.")

        issue_dir = Path("temp/issue_geojson")
        issue_dir.mkdir(parents=True, exist_ok=True)
        for j, (_, issue_feat) in enumerate(multi_polygon_issues):
            issue_path = issue_dir / f"issue_{j + 1}.geojson"
            with open(issue_path, "w") as f:
                json.dump({"type": "FeatureCollection", "features": [issue_feat]}, f)
            print(f"  - Written to: {issue_path}")
    elif processed > 0:
        print("\n✓ All processed features have single-polygon geometries.")

    # --- Write outputs ---
    hulls_collection = {"type": "FeatureCollection", "features": output_features_hulls}
    with open(OUTPUT_PATH_HULLS, "w") as f:
        json.dump(hulls_collection, f)
    print(f"Concave hulls written to: {OUTPUT_PATH_HULLS}")

    with_hulls_collection = {"type": "FeatureCollection", "features": output_features_with_hulls}
    with open(OUTPUT_PATH_WITH_HULLS, "w") as f:
        json.dump(with_hulls_collection, f)
    print(f"Original geometries with concave hulls written to: {OUTPUT_PATH_WITH_HULLS}")


if __name__ == "__main__":
    main()
