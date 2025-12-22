#!/usr/bin/env python3
"""
04_copy_triangle_images.py

Copy combined images of parks with high triangularity (>= 0.8) to a dedicated folder.
Reads from 2a_parks_triangles_geometry.geojson and copies from images/ to images/triangles/.
"""

import json
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
INPUT_FILE = Path("./output_data/2a_parks_triangles_geometry.geojson")
IMAGES_DIR = Path("./images")
OUTPUT_DIR = IMAGES_DIR / "triangles"

# Threshold for triangularity
TRIANGULARITY_THRESHOLD = 0.2

# Video export options
EXPORT_VIDEO = True
VIDEO_FPS = 24  # Frames per second for the slideshow


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


def main():
    console.print("[bold cyan]04_copy_triangle_images.py[/bold cyan]")
    console.print(f"[dim]Triangularity threshold: {TRIANGULARITY_THRESHOLD}[/dim]")
    if EXPORT_VIDEO:
        console.print(f"[yellow]Video export enabled ({VIDEO_FPS} fps)[/yellow]")
    console.print()

    # Load input data
    console.print(f"[cyan]Loading {INPUT_FILE}...[/cyan]")
    with open(INPUT_FILE) as f:
        data = json.load(f)

    features = data["features"]
    console.print(f"[dim]Loaded {len(features)} features[/dim]")

    # Filter by triangularity
    high_triangularity = [
        f
        for f in features
        if (f["properties"].get("ta_triangularity") or 0) >= TRIANGULARITY_THRESHOLD
    ]
    console.print(
        f"[green]Found {len(high_triangularity)} parks with triangularity >= {TRIANGULARITY_THRESHOLD}[/green]\n"
    )

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Sort by triangularity descending for consistent ordering
    high_triangularity.sort(
        key=lambda f: f["properties"].get("ta_triangularity", 0), reverse=True
    )

    # Copy images
    copied = 0
    missing = 0
    missing_parks = []
    copied_files = []  # Track copied files for video export

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Copying images...", total=len(high_triangularity)
        )

        for feature in high_triangularity:
            props = feature["properties"]
            park_id = props.get(":id", "")
            name311 = props.get("name311", "")
            triangularity = props.get("ta_triangularity", 0)

            # Format folder name
            folder_name = format_park_name(park_id, name311)

            # Source path
            source_folder = IMAGES_DIR / folder_name
            combined_image = source_folder / f"{folder_name}_combined.jpg"

            if combined_image.exists():
                # Copy with triangularity in filename for easy sorting
                dest_filename = f"{triangularity:.4f}_{folder_name}_combined.jpg"
                dest_path = OUTPUT_DIR / dest_filename
                shutil.copy2(combined_image, dest_path)
                copied_files.append(dest_path)
                copied += 1
            else:
                missing += 1
                missing_parks.append((folder_name, name311))

            progress.update(task, advance=1)

    # Export video if enabled
    video_path = None
    if EXPORT_VIDEO and copied_files:
        console.print("\n[cyan]Generating video with ffmpeg...[/cyan]")
        video_path = OUTPUT_DIR / "triangles.mp4"

        # Create a temporary file list for ffmpeg concat demuxer
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            temp_list = Path(f.name)
            # Sort files by name (which sorts by triangularity since it's the prefix)
            for img_path in sorted(copied_files, reverse=True):
                # Escape single quotes in path
                escaped_path = str(img_path.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
                f.write(f"duration {1/VIDEO_FPS}\n")
            # Add last file again (ffmpeg concat needs it for duration)
            if copied_files:
                last_file = sorted(copied_files, reverse=True)[-1]
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
                console.print(f"[red]ffmpeg error:[/red] {result.stderr}")
            else:
                console.print(f"[green]Video exported:[/green] {video_path}")
        finally:
            temp_list.unlink()  # Clean up temp file

    # Summary
    console.print()
    console.print("[bold green]Done![/bold green]")
    console.print(f"  [green]Copied: {copied} images[/green]")
    if missing > 0:
        console.print(f"  [yellow]Missing: {missing} images[/yellow]")
        if missing <= 10:
            for folder, name in missing_parks:
                console.print(f"    [dim]- {name} ({folder})[/dim]")
        else:
            console.print(f"    [dim](showing first 10)[/dim]")
            for folder, name in missing_parks[:10]:
                console.print(f"    [dim]- {name} ({folder})[/dim]")

    console.print(f"\n[cyan]Output directory:[/cyan] {OUTPUT_DIR}")
    if video_path and video_path.exists():
        console.print(f"[cyan]Video:[/cyan] {video_path}")

if __name__ == "__main__":
    main()
