#!/usr/bin/env python3
"""
Commute heatmaps with per-cell hour/min labels (e.g., 1h15m) +
weekday expected time bars (also hh:mm formatting).

Usage:
  python commute_heatmaps_prettyformat.py --csv next_week_commute_slots.csv --out charts [--fontsize 6]
"""

import argparse
from pathlib import Path
import numpy as np
import pandas as pd  # type: ignore[import]
import matplotlib.pyplot as plt


def parse_args():
    p = argparse.ArgumentParser(
        description="Commute heatmaps with HHhMMm cell labels + weekday medians"
    )
    p.add_argument(
        "--csv",
        default="next_week_commute_slots.csv",
        help="Path to the commute CSV with durations",
    )
    p.add_argument("--out", default="charts", help="Output directory for PNGs")
    p.add_argument(
        "--fontsize", type=float, default=6.0, help="Font size for heatmap cell labels"
    )
    return p.parse_args()


def parse_duration_minutes(val) -> float:
    # Convert "3720s" → 62.0
    if isinstance(val, str) and val.endswith("s"):
        try:
            return int(val[:-1]) / 60.0
        except Exception:
            return np.nan
    return np.nan


def fmt_minutes_to_human(mins: float) -> str:
    """Convert minutes into:
    0h08m → '08m'
    1h40m → '1h\n40m'
    """
    if mins is None or (isinstance(mins, float) and np.isnan(mins)):
        return ""
    mins = int(round(float(mins)))
    h = mins // 60
    m = mins % 60

    if h == 0:
        # Only minutes
        return f"{m:02d}m"
    else:
        # Hours on first line, minutes on second
        return f"{h}h\n{m:02d}m"


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def make_heatmap_with_labels(
    d: pd.DataFrame, direction_label: str, outdir: Path, fontsize: float
):
    if d.empty:
        return None

    # Weekday mapping and order
    weekday_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    d["weekday_num"] = d["ts"].dt.weekday
    d["weekday"] = d["weekday_num"].map(weekday_map)  # type: ignore[arg-type]
    weekday_order = ["Mon", "Tue", "Wed", "Thu", "Fri"]

    # Time-of-day label as HH:MM
    d["time_hm"] = d["ts"].dt.strftime("%H:%M")

    times_sorted = sorted(d["time_hm"].unique())

    # Median minutes pivot
    pivot = d.pivot_table(
        index="weekday", columns="time_hm", values="minutes", aggfunc="median"
    )
    pivot = pivot.reindex(index=weekday_order, columns=times_sorted)

    # Plot heatmap
    fig, ax = plt.subplots(figsize=(13, 5))
    im = ax.imshow(pivot.values, aspect="auto")  # default colormap

    monday = d["ts"].dt.date.min()
    friday = d["ts"].dt.date.max()
    title_range = f"{monday:%b. %d} – {friday:%b. %d}"

    hours = d["ts"].dt.hour

    if hours.max() <= 14:
        period_label = "Morning"
    else:
        period_label = "Evening"

    ax.set_title(f"{period_label} | {direction_label} | {title_range}")
    ax.set_xlabel(f"Departure time (leave at)")

    ax.set_ylabel("Weekday")

    # Y ticks
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels(pivot.index)

    # X ticks (reduce crowding)
    ncols = len(pivot.columns)
    if ncols > 0:
        step = max(1, ncols // 16)  # target ~16 ticks
        xticks = np.arange(0, ncols, step)
        ax.set_xticks(xticks)
        ax.set_xticklabels(
            [str(pivot.columns[int(i)]) for i in xticks], rotation=45, ha="right"
        )

    # Overlay human-readable labels
    data = pivot.values
    nrows, ncols = data.shape
    for i in range(nrows):
        for j in range(ncols):
            val = data[i, j]
            if isinstance(val, float) and np.isnan(val):
                continue
            # ax.text(j, i, fmt_minutes_to_human(val), ha="center", va="center", fontsize=fontsize)
            # Get the background color RGBA for this cell
            rgba = im.cmap(im.norm(val))
            r, g, b, _ = rgba

            # Compute luminance (perceptual brightness)
            luminance = 0.299 * r + 0.587 * g + 0.114 * b

            # Choose white or black depending on brightness
            text_color = "black" if luminance > 0.5 else "white"

            ax.text(
                j,
                i,
                fmt_minutes_to_human(val),
                ha="center",
                va="center",
                fontsize=fontsize,
                color=text_color,
            )

    # Colorbar in minutes
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Minutes")

    fig.tight_layout()
    safe = direction_label.replace(" ", "").replace("→", "to")
    out_path = outdir / f"heatmap_pretty_{safe}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main():
    args = parse_args()
    csv_path = Path(args.csv)
    outdir = Path(args.out)
    ensure_dir(outdir)

    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    # Load
    df = pd.read_csv(csv_path)

    # Filter to rows with durations and timestamps
    df["minutes"] = df["duration"].apply(parse_duration_minutes)
    df = df[df["minutes"].notna()]  # type: ignore[assignment]
    df["ts"] = pd.to_datetime(df["departure_time_rfc3339"], errors="coerce")
    df = df[df["ts"].notna()]  # type: ignore[assignment]

    # Display-friendly direction labels
    df["direction"] = df["direction"].replace(  # type: ignore[assignment]
        {"H2W": "Home → Work", "W2H": "Work → Home"}
    )

    outputs = []
    for label in sorted(df["direction"].dropna().unique()):  # type: ignore[attr-defined]
        ddir = df[df["direction"] == label].copy()
        hpath = make_heatmap_with_labels(ddir, label, outdir, fontsize=args.fontsize)  # type: ignore[arg-type]
        if hpath:
            outputs.append(str(hpath))

    if outputs:
        print("Wrote:")
        for p in outputs:
            print(" -", p)
    else:
        print("No charts produced (no valid rows).")


if __name__ == "__main__":
    main()
