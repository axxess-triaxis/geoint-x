# Scheduler backtest (real Sentinel-2 acquisition catalogue)

Generated 2026-09-28 08:14 UTC by `scripts/backtest_scheduler.py`. 3 areas: Deepor Beel wetland, Guwahati (472 acquisitions), Amingaon - Changsari corridor, North Guwahati (472 acquisitions), Majuli river island, south bank (465 acquisitions).

One analysis per week, chosen among acquisitions that actually occurred over each area in the preceding 7 days. Usable = scene cloud <= 20%. Change likelihood held neutral (no ground truth). Each year is a paired comparison.

## Per-year results

| Year | Strategy | Usable analyses | Usable share | Mean staleness (d) | Worst staleness (d) | Coverage evenness |
|---|---|---|---|---|---|---|
| 2020 | round_robin | 11 | 0.21 | 83.8 | 246 | 0.896 |
| 2020 | clearest_scene | 22 | 0.42 | 73.8 | 233 | 0.996 |
| 2020 | marginal_value | 21 | 0.40 | 68.8 | 228 | 0.987 |
| 2020 | marginal_value_cost_aware | 20 | 0.38 | 69.8 | 240 | 0.758 |
| 2021 | round_robin | 15 | 0.28 | 75.4 | 227 | 0.974 |
| 2021 | clearest_scene | 26 | 0.49 | 55.2 | 211 | 0.963 |
| 2021 | marginal_value | 26 | 0.49 | 50.9 | 193 | 0.988 |
| 2021 | marginal_value_cost_aware | 25 | 0.47 | 58.4 | 207 | 0.758 |
| 2022 | round_robin | 5 | 0.83 | 156.1 | 366 | 0.926 |
| 2022 | clearest_scene | 5 | 0.83 | 168.7 | 394 | 0.490 |
| 2022 | marginal_value | 5 | 0.83 | 156.5 | 366 | 0.926 |
| 2022 | marginal_value_cost_aware | 5 | 0.83 | 163.0 | 380 | 0.758 |
| 2023 | round_robin | 19 | 0.36 | 66.9 | 240 | 0.978 |
| 2023 | clearest_scene | 28 | 0.53 | 39.5 | 151 | 0.961 |
| 2023 | marginal_value | 28 | 0.53 | 41.4 | 172 | 0.982 |
| 2023 | marginal_value_cost_aware | 27 | 0.51 | 47.6 | 193 | 0.813 |
| 2024 | round_robin | 17 | 0.32 | 66.3 | 227 | 0.954 |
| 2024 | clearest_scene | 21 | 0.40 | 64.1 | 211 | 0.850 |
| 2024 | marginal_value | 20 | 0.38 | 57.4 | 211 | 0.980 |
| 2024 | marginal_value_cost_aware | 20 | 0.38 | 63.1 | 220 | 0.823 |
| 2025 | round_robin | 18 | 0.34 | 84.5 | 288 | 0.947 |
| 2025 | clearest_scene | 23 | 0.43 | 74.9 | 253 | 0.933 |
| 2025 | marginal_value | 22 | 0.42 | 75.3 | 256 | 0.984 |
| 2025 | marginal_value_cost_aware | 22 | 0.42 | 92.7 | 352 | 0.616 |

## Paired differences vs round robin (mean over years, with per-year range)

| Strategy | Metric | Mean delta | Min | Max | Years better |
|---|---|---|---|---|---|
| clearest_scene | usable_analyses | +6.67 | +0.00 | +11.00 | 5/6 |
| clearest_scene | usable_share | +0.13 | +0.00 | +0.21 | 5/6 |
| clearest_scene | mean_staleness_days | -9.49 | -27.45 | +12.57 | 5/6 |
| clearest_scene | worst_staleness_days | -23.50 | -89.00 | +28.00 | 5/6 |
| clearest_scene | coverage_evenness | -0.08 | -0.44 | +0.10 | 1/6 |
| marginal_value | usable_analyses | +6.17 | +0.00 | +11.00 | 5/6 |
| marginal_value | usable_share | +0.12 | +0.00 | +0.21 | 5/6 |
| marginal_value | mean_staleness_days | -13.79 | -25.50 | +0.44 | 5/6 |
| marginal_value | worst_staleness_days | -28.00 | -68.00 | +0.00 | 5/6 |
| marginal_value | coverage_evenness | +0.03 | +0.00 | +0.09 | 5/6 |
| marginal_value_cost_aware | usable_analyses | +5.67 | +0.00 | +10.00 | 5/6 |
| marginal_value_cost_aware | usable_share | +0.11 | +0.00 | +0.19 | 5/6 |
| marginal_value_cost_aware | mean_staleness_days | -6.44 | -19.28 | +8.14 | 4/6 |
| marginal_value_cost_aware | worst_staleness_days | -0.33 | -47.00 | +64.00 | 4/6 |
| marginal_value_cost_aware | coverage_evenness | -0.19 | -0.33 | -0.13 | 0/6 |

## Reading this honestly

- This replay evaluates observation logistics only. It cannot show whether the agent finds more real change, because there is no labelled change ground truth for these areas.
- Scene-level cloud cover is a proxy; the live agent uses the measured AOI clear fraction (SCL).
- Results are reported as produced, including metrics where the baseline is better.
- History: the first version of the agent divided value by processing cost (area in megapixels). This backtest showed it starved the largest area (worse coverage evenness than round robin in every year), so cost-awareness is now off by default. The cost-aware variant is kept in this table for comparison.
