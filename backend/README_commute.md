
# Commute Time Grapher (Typical Traffic via Google Maps)

This script estimates *typical* commute times from your work to your home using Google's traffic model.
Since Google only returns traffic-aware times for **now or the future**, the script queries a grid of
**future** departure times across upcoming weekdays. These are backed by historical averages ("typical
traffic"), so they are a practical proxy for real-world historical conditions.

**Route:** 650 California St, San Francisco, CA → 4585 Thousand Oaks Dr, San Jose, CA

## What you get

- `commute_output/commute_times.csv` — one row per sampled departure time, with duration, arrival time,
  and a Boolean for "late after 7pm".
- `commute_output/commute_heatmap.png` — heatmap of typical minutes by weekday × departure time.
- `commute_output/commute_average_line.png` — line chart of the weekday-average minutes vs departure time.

## How to run

1. **Get a Google Maps API key** with access to the Distance Matrix API.
2. Export it before running:
   ```bash
   export GOOGLE_MAPS_API_KEY="YOUR_KEY_HERE"
   ```
3. Run the script:
   ```bash
   python /mnt/data/fetch_and_plot_commute.py
   ```

By default, we sample 4:00–8:00 PM in 10-minute steps for the next 2 workweeks (Mon–Fri). You can adjust
those in the script: `START_HOUR`, `END_HOUR`, `STEP_MIN`, and `WEEKS_AHEAD`.

## Interpreting "how late I will be home"

The script flags `late_after_7pm = true` when the **estimated arrival time** exceeds **7:00 PM**.
Change `LATE_AT_TIME` in the script to use a different "late" threshold.

## Notes / caveats

- Google does **not** serve true past traffic. Future queries use a "typical" model derived from historical
  data, which is what we visualize here.
- If you want truly historical travel times for specific past dates (e.g., "every weekday in Sept 2025"),
  you’d need a vendor like TomTom Traffic Stats or HERE Historical Traffic, which are paid datasets.
  This script focuses on practical *typical* commute planning.
