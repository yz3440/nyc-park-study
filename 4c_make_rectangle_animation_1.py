#!/usr/bin/env python3
"""
4c_make_rectangle_animation_1.py

Create a video animation of elongated rectangular parks sorted by rotation.
Filters parks by rectangularity and aspect ratio thresholds,
then sorts by ra_mrr_rotation_degrees to create a rotating animation.
"""

import json
import subprocess
import shutil
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
ANALYSIS_FILE = Path("./output_data/2a_parks_concave_hull_analysis.geojson")
IMAGES_DIR = Path("./images")
OUTPUT_DIR = IMAGES_DIR / "rectangle_animation"

# Thresholds (configurable)
RECTANGULARITY_THRESHOLD = 0.8  # Minimum ra_rectangularity
ASPECT_RATIO_THRESHOLD = 2.0  # Minimum aspect ratio (max/min of width/height)

# Video export options
VIDEO_FPS = 12  # Frames per second for the slideshow


# SUFFIX = "_combined"
SUFFIX = ""


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


def main():
    console.print("[bold cyan]4c_make_rectangle_animation_1.py[/bold cyan]")
    console.print(f"[dim]Rectangularity threshold: >= {RECTANGULARITY_THRESHOLD}[/dim]")
    console.print(f"[dim]Aspect ratio threshold: >= {ASPECT_RATIO_THRESHOLD}[/dim]")
    console.print(f"[dim]Video FPS: {VIDEO_FPS}[/dim]")
    console.print()

    # Load analysis file
    console.print(f"[cyan]Loading {ANALYSIS_FILE}...[/cyan]")
    with open(ANALYSIS_FILE) as f:
        data = json.load(f)

    console.print(f"[dim]Total features: {len(data['features'])}[/dim]")

    # Filter and process
    rectangles = []
    skipped_rectangularity = 0
    skipped_aspect_ratio = 0
    skipped_missing_data = 0

    for feat in data["features"]:
        props = feat["properties"]
        park_id = props.get(":id")

        rectangularity = props.get("ra_rectangularity")
        width = props.get("ra_mrr_width")
        height = props.get("ra_mrr_height")
        rotation = props.get("ra_mrr_rotation_degrees")

        # Check for missing data
        if (
            rectangularity is None
            or width is None
            or height is None
            or rotation is None
        ):
            skipped_missing_data += 1
            continue

        # Filter by rectangularity
        if rectangularity < RECTANGULARITY_THRESHOLD:
            skipped_rectangularity += 1
            continue

        # Calculate aspect ratio (always bigger / smaller)
        aspect_ratio = (
            max(width, height) / min(width, height) if min(width, height) > 0 else 0
        )

        # Filter by aspect ratio
        if aspect_ratio < ASPECT_RATIO_THRESHOLD:
            skipped_aspect_ratio += 1
            continue

        rectangles.append(
            {
                "park_id": park_id,
                "name311": props.get("name311", ""),
                "signname": props.get("signname", ""),
                "rectangularity": rectangularity,
                "aspect_ratio": aspect_ratio,
                "width": width,
                "height": height,
                "rotation": rotation,
            }
        )

    console.print(f"[green]Found {len(rectangles)} elongated rectangles[/green]")
    console.print(
        f"[dim]Skipped: {skipped_rectangularity} (low rectangularity), {skipped_aspect_ratio} (low aspect ratio), {skipped_missing_data} (missing data)[/dim]"
    )

    if len(rectangles) == 0:
        console.print(
            "[yellow]No rectangles found matching criteria. Try lowering thresholds.[/yellow]"
        )
        return

    # Sort by rotation (0 to 180 degrees typically)
    rectangles.sort(key=lambda r: r["rotation"])

    # Show rotation distribution
    console.print("\n[cyan]Rotation distribution (degrees):[/cyan]")
    buckets = [0] * 6  # 0-30, 30-60, 60-90, 90-120, 120-150, 150-180
    for r in rectangles:
        bucket = min(int(r["rotation"] / 30), 5)
        buckets[bucket] += 1
    ranges = ["0-30°", "30-60°", "60-90°", "90-120°", "120-150°", "150-180°"]
    for rng, count in zip(ranges, buckets):
        bar = "█" * (count // 2) if count > 0 else ""
        console.print(f"  {rng:10} {count:3} {bar}")

    # Show aspect ratio distribution
    console.print("\n[cyan]Aspect ratio distribution:[/cyan]")
    ar_buckets = {"2-3": 0, "3-4": 0, "4-5": 0, "5-10": 0, "10+": 0}
    for r in rectangles:
        ar = r["aspect_ratio"]
        if ar < 3:
            ar_buckets["2-3"] += 1
        elif ar < 4:
            ar_buckets["3-4"] += 1
        elif ar < 5:
            ar_buckets["4-5"] += 1
        elif ar < 10:
            ar_buckets["5-10"] += 1
        else:
            ar_buckets["10+"] += 1
    for rng, count in ar_buckets.items():
        bar = "█" * (count // 2) if count > 0 else ""
        console.print(f"  {rng:6} {count:3} {bar}")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Copy images in rotation order
    console.print(f"\n[cyan]Copying images in rotation order...[/cyan]")
    copied_files = []
    missing_images = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Copying...", total=len(rectangles))

        for idx, r in enumerate(rectangles):
            folder_name = format_park_name(r["park_id"], r["name311"])
            source_folder = IMAGES_DIR / folder_name
            combined_image = source_folder / f"{folder_name}{SUFFIX}.jpg"

            if combined_image.exists():
                # Copy with sequence number for ordering
                dest_filename = f"{idx:04d}_{r['rotation']:06.2f}deg_ar{r['aspect_ratio']:.1f}_{folder_name}{SUFFIX}.jpg"
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
        video_path = OUTPUT_DIR / "rectangle_rotation_animation.mp4"

        # Create a temporary file list for ffmpeg concat demuxer
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            temp_list = Path(f.name)
            # Files are already sorted by rotation (via filename numbering)
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
