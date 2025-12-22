#!/usr/bin/env python3
"""
4b_make_triangle_animation.py

Create a video animation of triangle parks sorted by the orientation of their smallest angle.
Reads labeled parks from parks_with_triangle_labels.geojson,
gets triangle vertices from 2a_parks_concave_hull_analysis.geojson,
and creates a video sequence ordered by orientation (0 to 2π).
"""

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)

console = Console()

# Paths
LABELS_FILE = Path("./output_data/parks_with_triangle_labels.geojson")
ANALYSIS_FILE = Path("./output_data/2a_parks_concave_hull_analysis.geojson")
IMAGES_DIR = Path("./images")
OUTPUT_DIR = IMAGES_DIR / "triangle_animation"

# Labels to include
INCLUDE_LABELS = ["Definitely Triangle", "Most Likely a Triangle"]

# Video export options
VIDEO_FPS = 12  # Frames per second for the slideshow

SUFFIX = "_combined"
# SUFFIX = ""


def format_park_name(park_id: str, name311: str) -> str:
    """Format park name for filename: id followed by name311 (lowercase, dashed)"""
    if not name311:
        name311 = "unnamed"

    # Convert to lowercase and replace spaces/special characters with dashes
    name_formatted = name311.lower()
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


def calculate_angle_at_vertex(p_prev: list, p_curr: list, p_next: list) -> float:
    """
    Calculate the interior angle at p_curr formed by vectors to p_prev and p_next.
    Returns angle in radians.
    """
    # Vectors from current point to adjacent points
    v1 = (p_prev[0] - p_curr[0], p_prev[1] - p_curr[1])
    v2 = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])

    # Dot product and magnitudes
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    mag1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2)
    mag2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2)

    if mag1 == 0 or mag2 == 0:
        return math.pi  # Degenerate case

    # Clamp to avoid floating point errors with acos
    cos_angle = max(-1, min(1, dot / (mag1 * mag2)))
    return math.acos(cos_angle)


def calculate_bisector_orientation(p_prev: list, p_curr: list, p_next: list) -> float:
    """
    Calculate the orientation of the angle bisector at p_curr.
    Returns angle in radians from 0 to 2π.

    The bisector direction is the average of the two unit vectors pointing
    away from the vertex (into the triangle).
    """
    # Unit vectors from current point to adjacent points
    v1 = (p_prev[0] - p_curr[0], p_prev[1] - p_curr[1])
    v2 = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])

    mag1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2)
    mag2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2)

    if mag1 == 0 or mag2 == 0:
        return 0  # Degenerate case

    # Normalize
    u1 = (v1[0] / mag1, v1[1] / mag1)
    u2 = (v2[0] / mag2, v2[1] / mag2)

    # Bisector direction (average of unit vectors)
    bisector = (u1[0] + u2[0], u1[1] + u2[1])

    # Orientation using atan2 (returns -π to π, we convert to 0 to 2π)
    angle = math.atan2(bisector[1], bisector[0])
    if angle < 0:
        angle += 2 * math.pi

    return angle


def find_smallest_angle_orientation(vertices: list) -> tuple[float, float, int]:
    """
    Find the smallest angle in the triangle and return its orientation.

    Args:
        vertices: List of 3 [lon, lat] coordinates

    Returns:
        (smallest_angle, bisector_orientation, vertex_index)
    """
    if len(vertices) != 3:
        return (math.pi, 0, 0)  # Not a triangle

    smallest_angle = float("inf")
    orientation = 0
    smallest_idx = 0

    for i in range(3):
        p_prev = vertices[(i - 1) % 3]
        p_curr = vertices[i]
        p_next = vertices[(i + 1) % 3]

        angle = calculate_angle_at_vertex(p_prev, p_curr, p_next)

        if angle < smallest_angle:
            smallest_angle = angle
            orientation = calculate_bisector_orientation(p_prev, p_curr, p_next)
            smallest_idx = i

    return (smallest_angle, orientation, smallest_idx)


def main():
    console.print("[bold cyan]4b_make_triangle_animation.py[/bold cyan]")
    console.print(f"[dim]Including labels: {INCLUDE_LABELS}[/dim]")
    console.print(f"[dim]Video FPS: {VIDEO_FPS}[/dim]")
    console.print()

    # Load labels file
    console.print(f"[cyan]Loading {LABELS_FILE}...[/cyan]")
    with open(LABELS_FILE) as f:
        labels_data = json.load(f)

    # Filter by label
    labeled_ids = set()
    for feat in labels_data["features"]:
        label = feat["properties"].get("main_triangle_label")
        if label in INCLUDE_LABELS:
            labeled_ids.add(feat["properties"].get(":id"))

    console.print(f"[dim]Found {len(labeled_ids)} parks with matching labels[/dim]")

    # Load analysis file
    console.print(f"[cyan]Loading {ANALYSIS_FILE}...[/cyan]")
    with open(ANALYSIS_FILE) as f:
        analysis_data = json.load(f)

    # Match and process
    triangles = []
    missing_vertices = 0

    for feat in analysis_data["features"]:
        props = feat["properties"]
        park_id = props.get(":id")

        if park_id not in labeled_ids:
            continue

        vertices = props.get("ta_triangle_vertices")
        if not vertices or len(vertices) != 3:
            missing_vertices += 1
            continue

        smallest_angle, orientation, vertex_idx = find_smallest_angle_orientation(
            vertices
        )

        triangles.append(
            {
                "park_id": park_id,
                "name311": props.get("name311", ""),
                "signname": props.get("signname", ""),
                "smallest_angle": smallest_angle,
                "smallest_angle_deg": math.degrees(smallest_angle),
                "orientation": orientation,
                "orientation_deg": math.degrees(orientation),
                "vertex_idx": vertex_idx,
            }
        )

    console.print(f"[green]Processed {len(triangles)} triangles[/green]")
    if missing_vertices > 0:
        console.print(
            f"[yellow]Skipped {missing_vertices} parks without valid triangle vertices[/yellow]"
        )

    # Sort by orientation (0 to 2π)
    triangles.sort(key=lambda t: t["orientation"])

    # Show orientation distribution
    console.print("\n[cyan]Orientation distribution:[/cyan]")
    buckets = [0] * 8
    for t in triangles:
        bucket = int(t["orientation"] / (math.pi / 4)) % 8
        buckets[bucket] += 1
    directions = ["→ E", "↗ NE", "↑ N", "↖ NW", "← W", "↙ SW", "↓ S", "↘ SE"]
    for i, (d, count) in enumerate(zip(directions, buckets)):
        bar = "█" * (count // 2)
        console.print(f"  {d:6} {count:3} {bar}")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Copy images in orientation order
    console.print(f"\n[cyan]Copying images in orientation order...[/cyan]")
    copied_files = []
    missing_images = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Copying...", total=len(triangles))

        for idx, t in enumerate(triangles):
            folder_name = format_park_name(t["park_id"], t["name311"])
            source_folder = IMAGES_DIR / folder_name
            combined_image = source_folder / f"{folder_name}{SUFFIX}.jpg"

            if combined_image.exists():
                # Copy with sequence number for ordering
                dest_filename = f"{idx:04d}_{t['orientation_deg']:06.2f}deg_{folder_name}{SUFFIX}.jpg"
                dest_path = OUTPUT_DIR / dest_filename
                shutil.copy2(combined_image, dest_path)
                copied_files.append(dest_path)
            else:
                missing_images += 1

            progress.update(task, advance=1)

    console.print(f"[green]Copied {len(copied_files)} images[/green]")
    if missing_images > 0:
        console.print(f"[yellow]Missing {missing_images} images[/yellow]")

    # Generate video
    if copied_files:
        console.print("\n[cyan]Generating video with ffmpeg...[/cyan]")
        video_path = OUTPUT_DIR / "triangle_orientation_animation.mp4"

        # Create a temporary file list for ffmpeg concat demuxer
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            temp_list = Path(f.name)
            # Files are already sorted by orientation (via filename numbering)
            for img_path in sorted(copied_files):
                escaped_path = str(img_path.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
                f.write(f"duration {1/VIDEO_FPS}\n")
            # Add last file again (ffmpeg concat needs it for duration)
            if copied_files:
                last_file = sorted(copied_files)[-1]
                escaped_path = str(last_file.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",  # Overwrite output
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(temp_list),
                    "-vf",
                    "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    str(VIDEO_FPS),
                    str(video_path),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                console.print(f"[red]ffmpeg error:[/red] {result.stderr[:500]}")
            else:
                duration = len(copied_files) / VIDEO_FPS
                console.print(f"[green]Video exported:[/green] {video_path}")
                console.print(
                    f"[dim]Duration: {duration:.1f}s ({len(copied_files)} frames @ {VIDEO_FPS} fps)[/dim]"
                )
        finally:
            temp_list.unlink()  # Clean up temp file

    # Summary
    console.print("\n[bold green]Done![/bold green]")
    console.print(f"[cyan]Output directory:[/cyan] {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
