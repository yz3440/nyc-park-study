"""
NYC Parks Triangle Analysis Visualization
Visualize triangularity metrics from the concave hull analysis
"""

import json
from pathlib import Path
import plotly.graph_objects as go

print("Loading NYC Parks Concave Hull Analysis data...")
SOURCE_DATA_FILE = "./output_data/2a_parks_concave_hull_analysis.geojson"
IMAGES_DIR = Path("./images")

# Load the analysis data
with open(SOURCE_DATA_FILE, "r") as f:
    data = json.load(f)

print(f"Loaded {len(data['features'])} parks")


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


def get_image_folder(park_id, name311):
    """Get the folder path for a park's images"""
    folder_name = format_park_name(park_id, name311)
    return IMAGES_DIR / folder_name


def get_image_path(park_id, name311):
    """Get the path to the combined image for a park"""
    folder = get_image_folder(park_id, name311)
    folder_name = format_park_name(park_id, name311)
    return folder / f"{folder_name}_combined.jpg"


def load_overlay_data(park_id, name311, triangle_vertices_wgs84):
    """
    Load overlay data for a park from its metadata.json.
    Returns concave hull pixels and triangle pixels, or None if not available.
    """
    folder = get_image_folder(park_id, name311)
    metadata_path = folder / "metadata.json"

    if not metadata_path.exists():
        return None

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    # Get original geometry pixels from metadata
    original_geometry_pixels = None
    if "original_geometry" in metadata and "pixels" in metadata["original_geometry"]:
        pixels_data = metadata["original_geometry"]["pixels"]
        if pixels_data and len(pixels_data) > 0:
            # Collect all polygon exteriors (for multipolygons)
            original_geometry_pixels = []
            for poly in pixels_data:
                exterior = poly.get("exterior", [])
                if exterior:
                    original_geometry_pixels.append(exterior)

    # Get concave hull pixels from metadata
    concave_hull_pixels = None
    if "concave_hull" in metadata and "pixels" in metadata["concave_hull"]:
        pixels_data = metadata["concave_hull"]["pixels"]
        if pixels_data and len(pixels_data) > 0:
            exterior = pixels_data[0].get("exterior", [])
            if exterior:
                concave_hull_pixels = exterior

    # Convert triangle vertices from WGS84 to pixels
    triangle_pixels = None
    if (
        triangle_vertices_wgs84
        and "padded_bbox" in metadata
        and "image_dimensions" in metadata
    ):
        bbox = metadata["padded_bbox"]
        dims = metadata["image_dimensions"]

        west = bbox["west"]
        east = bbox["east"]
        north = bbox["north"]
        south = bbox["south"]
        width_px = dims["width_px"]
        height_px = dims["height_px"]

        triangle_pixels = []
        for lon, lat in triangle_vertices_wgs84:
            # Convert lat/lon to pixel coordinates
            x = (lon - west) / (east - west) * width_px
            y = (north - lat) / (north - south) * height_px  # y is inverted
            triangle_pixels.append([round(x, 2), round(y, 2)])

    return {
        "original_geometry": original_geometry_pixels,
        "concave_hull": concave_hull_pixels,
        "triangle": triangle_pixels,
        "width": metadata.get("image_dimensions", {}).get("width_px", 300),
        "height": metadata.get("image_dimensions", {}).get("height_px", 300),
    }


# MARK: Interactive Factor Analysis for Top 300 Parks

print("\nGenerating interactive factor analysis for top 300 parks...")

# Collect parks with all factor data
parks_with_factors = []
for feature in data["features"]:
    props = feature["properties"]
    if props.get("ta_triangularity") is not None:
        park_id = props.get(":id", "unknown")
        name311 = props.get("name311", "")
        image_path = get_image_path(park_id, name311)

        # Calculate waveform energy factor: 1 / (1 + total_energy)
        waveform_energy = props.get("ta_waveform_total_energy")
        waveform_energy_factor = (
            1 / (1 + waveform_energy) if waveform_energy is not None else None
        )

        parks_with_factors.append(
            {
                "id": park_id,
                "signname": props.get("signname", "Unknown"),
                "name311": name311,
                "triangularity": props["ta_triangularity"],
                "factor_ch_area_ratio": props.get(
                    "ta_triangularity_factor_ch_area_ratio"
                ),
                "factor_ch_intersection": props.get(
                    "ta_triangularity_factor_ch_intersection_area_ratio"
                ),
                "factor_leftout": props.get("ta_triangularity_factor_leftout"),
                "factor_waveform_energy": waveform_energy_factor,
                "waveform_total_energy": waveform_energy,
                "triangle_vertices": props.get("ta_triangle_vertices"),
                "image_path": str(image_path).lstrip("./"),
                "image_exists": image_path.exists(),
            }
        )

# Sort by triangularity (descending) and take top 300
parks_with_factors.sort(key=lambda x: x["triangularity"], reverse=True)
top_300_with_ranks = parks_with_factors[:300]

# Add original rank to each park
for i, p in enumerate(top_300_with_ranks):
    p["original_rank"] = i + 1

# Filter out parks with triangularity >= 1.0 (using threshold for float precision), but keep original ranks
top_300 = [p for p in top_300_with_ranks if p["triangularity"] < 0.9999]

print(f"  Found {len(parks_with_factors)} parks with triangularity values")
print(
    f"  Top 300 parks, filtered out {300 - len(top_300)} with triangularity >= 0.9999"
)
print(f"  Showing {len(top_300)} parks")

# Count how many have images
images_found = sum(1 for p in top_300 if p["image_exists"])
print(f"  Parks with images: {images_found}/{len(top_300)}")

# Load overlay data for each park
print("  Loading overlay data from metadata.json files...")
overlay_data = {}
overlays_loaded = 0
for p in top_300:
    overlay = load_overlay_data(p["id"], p["name311"], p["triangle_vertices"])
    if overlay:
        overlay_data[p["id"]] = overlay
        overlays_loaded += 1
print(f"  Loaded overlay data for {overlays_loaded}/{len(top_300)} parks")

if top_300:
    # Create x-axis indices (park rank)
    x = list(range(len(top_300)))

    # Extract factor values (only the factors used in the new triangularity formula)
    ids = [p["id"] for p in top_300]
    names = [p["signname"] for p in top_300]
    original_ranks = [p["original_rank"] for p in top_300]
    triangularities_top = [p["triangularity"] for p in top_300]
    ch_area_ratios = [p["factor_ch_area_ratio"] for p in top_300]
    ch_intersections = [p["factor_ch_intersection"] for p in top_300]
    leftouts = [p["factor_leftout"] for p in top_300]
    waveform_energy_factors = [p["factor_waveform_energy"] for p in top_300]
    waveform_energies = [p["waveform_total_energy"] for p in top_300]
    image_paths = [p["image_path"] for p in top_300]

    # Create customdata array for hover (id, name, original_rank, image_path, factors...)
    customdata = [
        [
            ids[i],
            names[i],
            original_ranks[i],
            image_paths[i],
            triangularities_top[i],
            ch_area_ratios[i],
            ch_intersections[i],
            leftouts[i],
            waveform_energy_factors[i],
            waveform_energies[i],
        ]
        for i in range(len(top_300))
    ]

    # Create interactive plot with plotly
    fig = go.Figure()

    # Add traces for each factor used in the triangularity formula:
    # triangularity = ch_area_ratio * intersection² * leftout * waveform_energy_factor

    fig.add_trace(
        go.Scatter(
            x=x,
            y=triangularities_top,
            mode="lines+markers",
            name="Triangularity (product)",
            line=dict(color="#2ecc71", width=3),
            marker=dict(size=6),
            customdata=customdata,
            hovertemplate="<b>:id=%{customdata[0]}</b><br>%{customdata[1]}<br>Rank: %{customdata[2]}<br>Value: %{y:.4f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=ch_area_ratios,
            mode="lines",
            name="CH Area Ratio",
            line=dict(color="#3498db", width=2),
            customdata=customdata,
            hovertemplate="<b>:id=%{customdata[0]}</b><br>%{customdata[1]}<br>Rank: %{customdata[2]}<br>Value: %{y:.4f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=ch_intersections,
            mode="lines",
            name="Intersection Ratio (×2)",
            line=dict(color="#e74c3c", width=2),
            customdata=customdata,
            hovertemplate="<b>:id=%{customdata[0]}</b><br>%{customdata[1]}<br>Rank: %{customdata[2]}<br>Value: %{y:.4f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=leftouts,
            mode="lines",
            name="Leftout Factor",
            line=dict(color="#9b59b6", width=2),
            customdata=customdata,
            hovertemplate="<b>:id=%{customdata[0]}</b><br>%{customdata[1]}<br>Rank: %{customdata[2]}<br>Value: %{y:.4f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=waveform_energy_factors,
            mode="lines",
            name="Waveform Energy Factor",
            line=dict(color="#f39c12", width=2),
            customdata=customdata,
            hovertemplate="<b>:id=%{customdata[0]}</b><br>%{customdata[1]}<br>Rank: %{customdata[2]}<br>Value: %{y:.4f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Top 300 Parks: Triangularity = CH_Area × Intersection² × Leftout × WaveformEnergy",
        xaxis_title="Park Rank (by Triangularity)",
        yaxis_title="Factor Value",
        yaxis=dict(range=[0, 1.05]),
        hovermode="x",
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="right",
            x=0.99,
        ),
        template="plotly_white",
    )

    # Generate the base HTML
    factor_plot_path = "./output_data/2b_triangularity_factors_top300.html"
    base_html = fig.to_html(include_plotlyjs=True, full_html=True)

    # Serialize overlay data to JSON for embedding in HTML
    overlay_json = json.dumps(overlay_data)

    # Inject custom CSS and JavaScript for image preview with SVG overlays
    custom_style = """
<style>
#image-preview {
    position: fixed;
    bottom: 70px;
    left: 20px;
    width: 450px;
    height: 450px;
    border: 3px solid #333;
    border-radius: 8px;
    background: #1a1a1a;
    display: none;
    z-index: 9999;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    overflow: hidden;
}
#image-preview .image-container {
    position: relative;
    width: 100%;
    height: 100%;
}
#image-preview img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}
#image-preview svg {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
}
#image-preview .no-image {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #888;
    font-family: sans-serif;
    font-size: 14px;
}
#image-info {
    position: fixed;
    bottom: 20px;
    left: 480px;
    width: 240px;
    padding: 10px 14px;
    background: #333;
    color: #fff;
    font-family: monospace;
    font-size: 11px;
    line-height: 1.6;
    border-radius: 4px;
    display: none;
    z-index: 9999;
}
#overlay-legend {
    position: fixed;
    bottom: 528px;
    left: 20px;
    padding: 6px 10px;
    background: rgba(0,0,0,0.7);
    color: #fff;
    font-family: sans-serif;
    font-size: 11px;
    border-radius: 4px;
    display: none;
    z-index: 9999;
}
#overlay-legend .legend-item {
    display: flex;
    align-items: center;
    margin: 3px 0;
}
#overlay-legend .legend-color {
    width: 16px;
    height: 16px;
    margin-right: 8px;
    border-radius: 2px;
}
</style>
"""

    # Serialize customdata for JavaScript
    customdata_json = json.dumps(customdata)

    custom_script = f"""
<div id="image-preview"></div>
<div id="image-info"></div>
<div id="overlay-legend">
    <div class="legend-item">
        <div class="legend-color" style="background: rgba(255,255,0,0.3);"></div>
        <span>Concave Hull</span>
    </div>
    <div class="legend-item">
        <div class="legend-color" style="background: rgba(128,0,128,0.3);"></div>
        <span>Original Shape</span>
    </div>
    <div class="legend-item">
        <div class="legend-color" style="background: transparent; border: 2px solid red;"></div>
        <span>Simplified Triangle</span>
    </div>
</div>
<div id="nav-hint" style="position:fixed;bottom:20px;left:20px;background:#333;color:#fff;padding:8px 12px;border-radius:4px;font-family:sans-serif;font-size:12px;z-index:9999;">
    Use ← → arrow keys to navigate parks
</div>
<script>
(function() {{
    var overlayData = {overlay_json};
    var allCustomData = {customdata_json};
    var currentIndex = 0;
    var totalParks = allCustomData.length;
    
    var imagePreview = document.getElementById('image-preview');
    var imageInfo = document.getElementById('image-info');
    var overlayLegend = document.getElementById('overlay-legend');
    var plotDiv = document.querySelector('.plotly-graph-div');
    
    if (!plotDiv) return;
    
    function showNoImage() {{
        imagePreview.innerHTML = '<div class="no-image">No image available</div>';
        overlayLegend.style.display = 'none';
    }}
    
    function pointsToSvgPath(points) {{
        if (!points || points.length < 2) return '';
        var path = 'M ' + points[0][0] + ' ' + points[0][1];
        for (var i = 1; i < points.length; i++) {{
            path += ' L ' + points[i][0] + ' ' + points[i][1];
        }}
        path += ' Z';
        return path;
    }}
    
    function createOverlaySvg(parkId, imgWidth, imgHeight) {{
        var data = overlayData[parkId];
        if (!data) return '';
        
        var origWidth = data.width || 300;
        var origHeight = data.height || 300;
        
        // Scale factor from original image to display size
        var scaleX = imgWidth / origWidth;
        var scaleY = imgHeight / origHeight;
        
        var svg = '<svg viewBox="0 0 ' + imgWidth + ' ' + imgHeight + '" preserveAspectRatio="none">';
        
        // Draw concave hull (yellow transparent fill, no stroke) - bottom layer
        if (data.concave_hull && data.concave_hull.length > 0) {{
            var scaledHull = data.concave_hull.map(function(p) {{
                return [p[0] * scaleX, p[1] * scaleY];
            }});
            svg += '<path d="' + pointsToSvgPath(scaledHull) + '" fill="rgba(255,255,0,0.3)" stroke="none"/>';
        }}
        
        // Draw original geometry (purple transparent fill, no stroke) - middle layer
        if (data.original_geometry && data.original_geometry.length > 0) {{
            for (var i = 0; i < data.original_geometry.length; i++) {{
                var scaledPoly = data.original_geometry[i].map(function(p) {{
                    return [p[0] * scaleX, p[1] * scaleY];
                }});
                svg += '<path d="' + pointsToSvgPath(scaledPoly) + '" fill="rgba(128,0,128,0.3)" stroke="none"/>';
            }}
        }}
        
        // Draw triangle (red stroke, no fill, on top) - top layer
        if (data.triangle && data.triangle.length > 0) {{
            var scaledTriangle = data.triangle.map(function(p) {{
                return [p[0] * scaleX, p[1] * scaleY];
            }});
            svg += '<path d="' + pointsToSvgPath(scaledTriangle) + '" fill="none" stroke="red" stroke-width="2"/>';
        }}
        
        svg += '</svg>';
        return svg;
    }}
    
    function displayPark(index) {{
        if (index < 0 || index >= totalParks) return;
        
        currentIndex = index;
        var customdata = allCustomData[index];
        
        var parkId = customdata[0];
        var parkName = customdata[1];
        var rank = customdata[2];
        var imagePath = customdata[3];
        
        // Convert relative path: images/... -> ../images/...
        var adjustedPath = '../' + imagePath;
        
        var container = document.createElement('div');
        container.className = 'image-container';
        
        var img = document.createElement('img');
        img.src = adjustedPath;
        img.onerror = showNoImage;
        img.onload = function() {{
            // Add SVG overlay after image loads
            var svgHtml = createOverlaySvg(parkId, 450, 450);
            if (svgHtml) {{
                container.insertAdjacentHTML('beforeend', svgHtml);
                overlayLegend.style.display = 'block';
            }}
        }};
        
        container.appendChild(img);
        imagePreview.innerHTML = '';
        imagePreview.appendChild(container);
        imagePreview.style.display = 'block';
        
        var triangularity = customdata[4];
        var chAreaRatio = customdata[5];
        var chIntersection = customdata[6];
        var leftout = customdata[7];
        var waveformEnergyFactor = customdata[8];
        var waveformEnergy = customdata[9];
        
        var formatVal = function(v) {{ return v != null ? v.toFixed(4) : 'N/A'; }};
        var formatEnergy = function(v) {{ return v != null ? v.toFixed(2) : 'N/A'; }};
        
        imageInfo.innerHTML = '<b>:id=' + parkId + '</b><br>' + parkName + '<br>Rank: ' + rank + ' / ' + totalParks +
            '<br><br><b>Formula:</b>' +
            '<br>CH_Area × Intersect² × Leftout × WaveE' +
            '<br><br><b>Factors:</b>' +
            '<br>Triangularity: ' + formatVal(triangularity) +
            '<br>─────────────────' +
            '<br>CH Area Ratio: ' + formatVal(chAreaRatio) +
            '<br>Intersection: ' + formatVal(chIntersection) + ' (×2)' +
            '<br>Leftout: ' + formatVal(leftout) +
            '<br>Waveform Energy: ' + formatVal(waveformEnergyFactor) +
            '<br><span style="color:#888">(raw energy: ' + formatEnergy(waveformEnergy) + ')</span>';
        imageInfo.style.display = 'block';
        
        // Highlight current point on chart
        Plotly.Fx.hover(plotDiv, [{{curveNumber: 0, pointNumber: index}}]);
    }}
    
    // Keyboard navigation
    document.addEventListener('keydown', function(e) {{
        if (e.key === 'ArrowRight') {{
            e.preventDefault();
            if (currentIndex < totalParks - 1) {{
                displayPark(currentIndex + 1);
            }}
        }} else if (e.key === 'ArrowLeft') {{
            e.preventDefault();
            if (currentIndex > 0) {{
                displayPark(currentIndex - 1);
            }}
        }}
    }});
    
    // Initialize with first park
    setTimeout(function() {{
        displayPark(0);
    }}, 500);
}})();
</script>
"""

    # Insert custom elements before closing </body>
    final_html = base_html.replace("</head>", custom_style + "</head>")
    final_html = final_html.replace("</body>", custom_script + "</body>")

    with open(factor_plot_path, "w") as f:
        f.write(final_html)

    print(f"  Saved interactive plot to: {factor_plot_path}")

print("\nDone!")
