# Methodology & Decision Log

## Queens Community Board 5 — DOT Safety Infrastructure Request Analysis

**Analysis period: 2020–2025** | **Current committed raw snapshot: 2026-10-09** | **Geography: QCB5 (Queens CD5)**

> **Publication readiness note:** Generated CSV tables and map layer exports in `output/` are the source of truth for current counts. This narrative has been aligned to the current committed outputs covered by local validation, but publication still requires human review of the curated Signal Studies subset, the `CQ25-0457B` raw-snapshot mismatch, the duplicate `CQ21-0749` rows, and the 10 unmatched signal-study geocodes.

---

## 1. Data Sources

The current committed raw CSV snapshot was produced in October 2026 (with crashes updated September 2026) using `scripts_fetch_data.py`. Re-fetching live NYC Open Data sources can change counts because source records continue to be updated.

| Dataset | Endpoint ID | File | Records | Date Range |
|---------|-------------|------|---------|------------|
| Signal Studies | `[w76s-c5u4]` | `data_raw/signal_studies_citywide.csv` | 76,748 | 1996–2026 |
| Speed Reducer Tracking System | `[9n6h-pt9g]` | `data_raw/srts_citywide.csv` | 60,937 | 1990–2026 |
| Motor Vehicle Collisions | `[h9gi-nx95]` | `data_raw/crashes_queens_2020plus.csv` | 9,967 | 2020–2026 (CB5 bounding-box injury/fatal candidates; 4,274 inside CB5 polygon for 2020–2025) |
| APS Installed Locations | `[de3m-c5p4]` | `data_raw/aps_installed_citywide.csv` | 4,404 | current installed inventory |
| CB5 Signal Studies | Derived | `output/data_cb5_signal_studies.csv` | 499 | 2020–2025 |

`output/data_cb5_signal_studies.csv` is a curated input rather than a file regenerated from raw source data. The current row-level provenance scaffold (`output/data_cb5_signal_studies_provenance.csv`) checks each curated row against the committed citywide Signal Studies snapshot by `id` and `referencenumber`: 495 rows match once, 3 curated rows for `CQ21-0749` match duplicate raw rows, and 1 curated row (`CQ25-0457B`) is not present in the committed raw snapshot. All 499 rows remain marked as needing human review; the scaffold does not by itself validate CB5 inclusion.

### 1.1 Analysis Time Window

**Primary analysis window: 2020–2025.** All charts, maps, and statistical tests use this window unless explicitly labeled otherwise.

**Rationale:**
- CB5 signal study data begins in January 2020 — there is no pre-2020 CB5 data in the Signal Studies dataset. Using 2020–2025 ensures apples-to-apples comparison between CB5 and citywide baselines.
- Data from early 2026 exists in some datasets but is excluded. 2026 is incomplete, and including a partial year would distort year-over-year trends and annualized rates.
- Current committed outputs use 2020–2025. The scripts compute the end year dynamically as the last complete calendar year (`date.today().year - 1`), so outputs will extend after a future data refresh unless an explicit analysis end year is added.

**Z-series charts** provide full historical context using each dataset's complete available range, capped at 2025. These are labeled with actual year ranges (e.g., "1999–2025"), never "Full History" or "All Years."

**Interpretation note:** The 2020–2025 window keeps CB5 and comparison records on the same period and avoids mixing current outputs with older records that may reflect different data coverage or policy context. Earlier records are provided as z-series context only.

---

## 2. Outcome Classification

### 2.1 Signal Studies

Signal study records are classified into three outcomes based on the `statusdescription` field:

| Outcome | Logic |
|---------|-------|
| **Denied** | Status contains "denial" OR status is "Engineering Study Completed" without any approval language |
| **Approved** | Status contains "approval", "approved", "aps installed", "aps ranking", or "aps design" |
| **Pending** | All other statuses (excluded from rate calculations) |

Only **resolved** records (denied + approved) are used for denial rate calculations.

**Classification note:** For this analysis, "Engineering Study Completed (Signals Engineering)" without approval language is classified as denied because it records a completed study with no approval status. This is an analytic classification, not a direct DOT status label.

### 2.2 Speed Bumps (SRTS)

SRTS records use the `segmentstatusdescription` field:

| Outcome | Value |
|---------|-------|
| **Denied** | "Not Feasible" |
| **Approved** | "Feasible" |

Only resolved records are included. SRTS outcomes are binary — DOT engineering determines feasibility, and the result is recorded directly.

---

## 3. Exclusions

### 3.1 Accessible Pedestrian Signals (APS)

APS requests are **excluded from all denial rate calculations**. APS installations are tracked in a separate installed-inventory dataset (`de3m-c5p4`) under a March 2022 remedial order. APS request and status records are not comparable to discretionary signal, stop-sign, LPI, left-turn, or speed-bump evaluations in this analysis. Including APS would mix a programmatic accessibility inventory with discretionary safety-request outcomes.

APS requests ARE included in volume/count charts (Charts 01, 01b) where they are visually distinguished with gray hatching and a legend note explaining the exclusion.

**Interpretation note:** Excluding APS keeps the denominator aligned to discretionary traffic-control and speed-reducer requests. The current generated outputs already report high denial rates for those non-APS request types, so APS should be shown as a separate inventory/count layer rather than folded into denial-rate calculations.

### 3.2 Borough Normalization

The `borough` field contains inconsistent values including codes ("QK", "MB", "9"), multi-borough entries ("All Boroughs", "S/Q"), and nulls. Records not matching the five standard boroughs are labeled "Unknown" in borough-level charts (29 records in 2020–2025, 0.16% of data).

### 3.3 SRTS 2020–2025 Filtering

For the interactive map and proximity analysis (Part 2), SRTS data is filtered to **2020–2025** to match the crash data and signal study windows. This excluded 1,528 pre-2020 SRTS records.

Chart 15 examines SRTS installation history using the full date range. It loads SRTS data via the shared `_load_cb5_srts_full()` helper, which applies the CB5 filtering pipeline (cb=405 + polygon filter) before any chart-specific year logic. Chart 01d (denied and approved counts) uses 2020–2025 for both signal studies and speed bumps.

**Rationale:** Crash data is only available from 2020 onward. Plotting a speed bump request denied in 2005 against crash data from 2020–2025 would create a misleading temporal mismatch. All data on the map shares the same 2020–2025 window.

---

## 4. CB5 Identification

All three datasets use geography-based filtering to ensure consistent CB5 boundaries.

### 4.1 Signal Studies

Signal Studies lack source coordinates and a community-board field, so the pipeline does not currently regenerate the CB5 subset from raw data. Instead it consumes a pre-filtered curated file (`output/data_cb5_signal_studies.csv`) containing 499 records. The provenance scaffold verifies whether each curated row can be traced to the committed citywide raw snapshot, but the row-level inclusion/exclusion rationale still requires human review before publication. See `REFERENCE_cb5_boundaries.md` for boundary filtering rules used by geography-enabled datasets and for known CB5 boundary pitfalls.

### 4.2 Speed Bumps (SRTS)

CB5 is identified by `cb = '405'` (borough code 4 for Queens + district 05) **plus** a mandatory polygon boundary filter:

1. **Polygon boundary filter**: All records with coordinates are tested against the official CB5 community district polygon (`data_raw/cb5_boundary.geojson`). The polygon is the **sole geographic authority** — no street-name heuristics. Impact: 28 resolved records excluded that pass `cb=405` but fall outside the actual CB5 polygon.

**CRITICAL:** Both layers (cb=405 + polygon filter) must be applied together. The `cb=405` field alone includes 28 resolved records outside the actual CB5 polygon. In `generate_maps.py`, the shared `_load_cb5_srts_full()` helper centralizes this pipeline so all SRTS charts use identical filtering. In `generate_charts.py`, the `prepare_data()` function applies the same two-layer pipeline.

*Note: A cross-street exclusion filter was previously applied but was removed in Feb 2026 after audit revealed it wrongly excluded 67 valid records inside the CB5 polygon (Maspeth area: 52 Ave, 53 Ave, Calamus Ave, Maurice Ave). Boundary streets are partly inside the polygon and must not be excluded by name.*

**Current count (all years):** 2,170 resolved `cb=405` SRTS records -> 2,142 retained after polygon filtering, with 28 excluded. **After 2020–2025 filter (map pipeline):** 436 records.

### 4.3 Motor Vehicle Crashes

The crash dataset has no community board field. CB5 crashes are identified using **point-in-polygon testing** against the official community district boundary. **Rows without valid coordinates are excluded** from the polygon filter (they cannot be geographically verified).

**Previous approach (replaced):** An SRTS-derived bounding box was used initially but audit revealed 24% false positives (980 of 4,084 crashes were outside the actual CB5 polygon but inside the bounding rectangle). The polygon filter eliminated all false positives.

**Coordinate exclusion fix (Feb 2026):** The `_filter_points_in_cb5()` function previously included rows without coordinates in the output by default, inflating crash counts from 3,213 to 3,938 (+725 rows). These no-coordinate rows did not affect proximity analysis (NaN distances are excluded from haversine calculations) but inflated the n= counts displayed in chart titles. Fixed in both `generate_charts.py` and `generate_maps.py`.

### 4.4 Geographic Boundary

All geographic filtering uses the **official NYC community district polygon** for Queens CD5, sourced from the NYC Department of City Planning via the [nycehs/NYC_geography](https://github.com/nycehs/NYC_geography) GitHub repository (51-point polygon, GeoJSON format). The polygon is cached locally at `data_raw/cb5_boundary.geojson` and auto-downloaded if missing.

Point-in-polygon testing uses Shapely with prepared geometry for performance. All coordinate-bearing records (crashes, SRTS, geocoded signal studies) are filtered against this polygon.

---

## 5. Part 1 Charts: Request Outcomes and Volume Analysis

Part 1 (`generate_charts.py`) answers the question: **What are CB5's chances when it asks DOT for safety infrastructure?**

### Chart 01: Signal Study Request Volume by Borough

Chart 01 (`chart_01_request_volume_by_borough.png`) presents a dual-panel view of signal study request volume for the 2020–2025 period. The left panel, "Citywide Signal Study Requests by Borough," displays a horizontal bar chart of total signal study requests per borough (n=17,824 citywide). Queens leads with 6,486 requests — more than any other borough. The right panel, "QCB5 Signal Study Requests by Type," breaks down CB5's 499 requests by type: Traffic Signal (178) and All-Way Stop (163) dominate the mix. APS requests are visually distinguished with hatching but are not excluded from volume counts; the APS exclusion applies only to rate calculations.

This chart establishes that Queens — and CB5 specifically — is an active requester of safety infrastructure. High request volume combined with high denial rates (shown in subsequent charts) indicates persistent unmet demand, not lack of engagement. A z-series companion (Chart 01z) provides the full history from 1996–2025.

### Chart 01b: Signal Study Request Trends by Year

Chart 01b (`chart_01b_requests_by_year.png`) tracks request volume trends over time in a two-panel layout for 2020–2025. The left panel is a line chart comparing Queens (navy blue) to citywide (goldenrod) trends; both show a peak in 2022 followed by decline. The right panel uses stacked bars to show the request type composition per year, with colors drawn from the project palette (navy for Traffic Signal, goldenrod for All-Way Stop, green for LPI, red for Left Turn, gray for APS).

The 2022 peak and subsequent decline could reflect several factors, including demand, outreach, reporting practices, or discouragement after sustained high denial rates; this analysis does not identify a cause. The type composition shift toward a growing APS share is treated separately from discretionary request outcomes. A z-series companion (Chart 01bz) provides the full history from 1996–2025 as a line chart.

### Chart 01c: QCB5 Requests by Type

Chart 01c (`chart_01c_cb5_requests_by_type.png`) breaks down QCB5's signal study requests by type as a horizontal bar chart (n=499, 2020–2025). This chart provides the type-level detail for QCB5 specifically, complementing Chart 01's right panel by showing request counts per type with year-over-year composition in an accompanying data table (`table_01c_cb5_requests_by_type_year.csv`).

### Chart 01d: QCB5 DOT Request Outcomes — Denied and Approved

Chart 01d (`chart_01d_denied_vs_approved.png`) presents the aggregate outcome counts for QCB5 safety requests in a two-panel layout, both covering 2020–2025. The left panel shows Signal Studies (excluding APS) with denied and approved counts labeled on red and green bars, plus an annotation box with the approval rate. The right panel shows Speed Bumps with the same layout — "Not Feasible" mapped to Denied and "Feasible" mapped to Approved. The current generated table (`table_01d_denied_vs_approved.csv`) reports 390 denied and 42 approved signal studies excluding APS, and 430 denied and 6 approved speed bump requests. The map/proximity subset is smaller for signal studies because only geocoded rows enter the map and proximity analysis.

This is the only chart that presents the raw headline numbers: denied and approved requests for each infrastructure type. While other charts show denial *rates* by borough (Chart 02), by request type (Chart 04), or over time (Chart 03), this chart shows the underlying numerator and denominator used for the headline outcome comparison. The disparity between denied and approved counts is descriptive and should be read alongside the sample sizes.

### Chart 02: Denial Rates by Borough

Chart 02 (`chart_02_denial_rates_by_borough.png`) displays signal study denial rates across all five boroughs as a horizontal bar chart (n=16,356 resolved records, excluding APS, 2020–2025). Queens is highlighted in dark navy, and a goldenrod dashed line marks the citywide average. Manhattan leads at 94.9%, while Queens is 88.9% compared with a citywide average of 88.6%. Every borough exceeds 78%, with the lowest (Bronx, 78.5%) denying more than three-quarters of requests.

The denial rate is not a local anomaly in this snapshot: every borough has a high denial rate, and Queens is close to the citywide average. This supports comparing CB5 with citywide practices rather than treating CB5 as an isolated case.

### Chart 03: Year-over-Year Trends

Charts 03a-03d (`chart_03a_signal_volume.png`, `chart_03b_signal_denial_rates.png`, `chart_03c_srts_volume.png`, and `chart_03d_srts_denial_rates.png`) track QCB5 trends across 2020-2025. Signal Studies and Speed Bumps each have separate request-volume and denial-rate charts. The denial-rate charts include a goldenrod dashed citywide comparison line. Signal study denial rates fluctuate between 79% and 100%, while speed bump denial rates have steadily climbed to 100% by 2025. The citywide trend mirrors CB5.

The convergence toward 100% denial for speed bumps is a major trend in the current outputs. In years with no approvals, the request process is still accepting applications but not producing feasible outcomes in the observed CB5 records. This suggests the evaluation criteria should be reviewed against community safety concerns and documented crash exposure. A z-series companion (Chart 03z) provides the full history: signal studies from 2020 (CB5 data start) and SRTS from 1999–2025.

### Chart 04: Denial Rates by Request Type

Chart 04 (`chart_04_denial_rates_by_request_type.png`) compares QCB5 and citywide denial rates across five request types using a grouped bar chart (navy for QCB5, goldenrod for citywide), with individual sample sizes shown per type on the x-axis labels. The data covers resolved records excluding APS for 2020–2025. Left Turn Arrow/Signal and Leading Pedestrian Interval are denied at 100% for both CB5 and citywide. Traffic Signal and All-Way Stop denials hover between 85% and 91%. Speed bumps are denied at 99% in CB5 and 95% citywide. Filtering to 2020–2025 was critical for this chart — the original all-time comparison used 1996–2025 citywide data against 2020–2025 CB5 data, creating an apples-to-oranges distortion.

The 100% denial rate for certain request types means there are no approvals for those categories in the current 2020–2025 resolved snapshot. That pattern should be interpreted with the sample sizes and analysis window shown on the chart, and it warrants review of whether the request process gives applicants realistic guidance about likely outcomes.

### Chart 05: Speed Bump (SRTS) Analysis

Charts 05a-05c (`chart_05a_queens_cb_denial_rates.png`, `chart_05b_denial_reasons.png`, and `chart_05c_denial_reasons_by_year.png`) provide the QCB5 speed bump outcome deep dive for 2020-2025. Chart 05a compares CB5's denial rate against other Queens community boards, where CB5 ranks near the top. Chart 05b breaks down CB5 denial reasons, showing that "Speed < 30 mph" accounts for 84.7% (364 of 430) of all denials. Chart 05c tracks this dominant reason over time as a stacked bar: the "Speed < 30 mph" share grew across the period, increasingly crowding out all other denial reasons.

This chart shows that one recorded denial reason, "Speed < 30 mph," accounts for most QCB5 speed-bump denials in 2020–2025. That DOT engineering criterion reflects **measured 85th-percentile radar travel speed below 30 mph** (not NYC's 25 mph default posted speed limit), while community safety concerns may also involve crashes, pedestrian conflicts, and street design. A z-series companion (Chart 05z) provides the full SRTS history from 1999–2025 with minimum-n thresholds.

### Chart 06: Most Denied Intersections

Chart 06 (`chart_06_most_denied_intersections.png`) ranks the top 10 QCB5 intersections by denial count for 2020–2025. Administrative duplicates sharing a DOT external reference number are collapsed to one record per unique reference before counting; this de-duplication removed 7 records (most notably, Metropolitan Ave & Flushing Ave dropped from 7 apparent denials to 3 genuine denials). Street pairs are also normalized to NYC DCP LION-aligned Title Case (`street_norm.py`) and sorted alphabetically so reversed filings ("Forest Ave & Metropolitan Ave" and "Metropolitan Ave & Forest Ave") combine cleanly. After de-duplication and canonical street pairing, Forest Ave & Metropolitan Ave leads with 6 separate denials, followed by Eliot Ave & Woodhaven Blvd and Cooper Ave & Cypress Ave with 5 each.

Repeated denials at the same intersection indicate persistent request activity with repeated denied outcomes. Where those locations also have high crash exposure, the results raise a concrete review question: whether the engineering criteria and documented safety risk are aligned.

### Chart 07: Most Denied Streets for Speed Bumps

Chart 07 (`chart_07_most_denied_streets_speed_bumps.png`) ranks the top 10 QCB5 streets by speed bump denial count (n=430 denials, 2020–2025). Otto Road, Myrtle Avenue, and Woodward Avenue are tied at 14 denials each, with a more even distribution than signal study denials.

These are streets where multiple blocks were requested and denied. Because speed bump requests are per-block segments, repeated denials on one street indicate corridor-level demand with no feasible outcomes in the current resolved records.

### Chart 08: QCB5 Crash Hotspots

Charts 08a and 08b (`chart_08a_crash_count.png` and `chart_08b_crash_injuries.png`) examine QCB5 crash hotspots across n=4,274 injury and fatal crashes from 2020-2025. Chart 08a, "Top 10 Streets by Crash Count," ranks streets by number of crash incidents as horizontal bars, where each bar represents a unique collision event. Chart 08b, "Top 10 Streets by Persons Injured," uses stacked horizontal bars to rank streets by total persons injured, broken into three segments: Pedestrians, Cyclists, and Motorists.

The two panels differ because a single crash can injure multiple people. Metropolitan Ave, for example, has 197 crashes and 254 persons injured (approximately 1.3 per crash). The stacked breakdown shows which road users bear injuries on each corridor. Raw NYPD and DOT datasets contain mixed ALL-CAPS formatting and inconsistent street suffixes ("METROPOLITAN AVENUE" and "METROPOLITAN AVE", "JUNIPER BOULEVARD NORTH" and "JUNIPER BLVD N", "ST NICHOLAS AVE" and "SAINT NICHOLAS AVENUE"), so `street_norm.py` standardizes street and intersection names to canonical NYC DCP LION-aligned Title Case before grouping and map export. All 5,209 plotted map points are also cross-checked against the official NYC Department of City Planning (DCP) Bytes of the Big Apple `nycd` `BoroCD 405` boundary (100% inside the polygon or within a 50-meter border-avenue buffer; 0 out-of-district outliers).

This chart establishes the **crash baseline**: where injury crashes are recorded and which road users are injured. The pedestrian injury breakdown is relevant to the safety infrastructure analyzed here, but the chart is descriptive; overlaps between crash hotspots and denial hotspots identify locations for closer review rather than proving why individual decisions were made.

### Chart 12: Request Type Mix

Chart 12 (`chart_12_request_types_distribution.png`) compares the percentage distribution of request types between QCB5 (n=875) and citywide (n=30,920) using a grouped bar chart. All records are resolved and exclude APS, covering 2020–2025. CB5 and citywide have nearly identical speed bump shares (49.8% in CB5, 49.6% citywide). CB5 has slightly fewer Traffic Signal requests (20.8% in CB5, 28.3% citywide) and slightly more All-Way Stop (18.7% in CB5, 15.5% citywide) and LPI (6.4% in CB5, 2.8% citywide) requests.

CB5 is not an outlier in what it asks for in this resolved non-APS snapshot: the mix of requests closely mirrors citywide patterns. This does not support a simple explanation that CB5's high denial rates are caused by an unusual request mix.

---

## 6. Part 2 Charts: Crash-Denial Correlation Analysis

Part 2 (`generate_maps.py`) answers the question: **Do denied locations have more crashes than approved locations? And does DOT follow through when it does approve?**

### 6.1 Geocoding Signal Study Intersections

Signal study records have street names but no coordinates. A three-tier local geocoding approach was used (no external API):

| Tier | Method | Coverage |
|------|--------|----------|
| 1 | **Crash data matching** — Match `(mainstreet, crossstreet1)` to Queens crash `(on_street_name, off_street_name)` using median lat/lon of all crashes at that intersection | 61% (262) |
| 2 | **SRTS data matching** — Match to SRTS `(onstreet, fromstreet/tostreet)` endpoint coordinates, using the matching segment endpoint | 28% (119) |
| 3 | **Street-line intersection** — Linear regression through known points for each street, then geometric intersection | 9% (39) |
| Manual | **Reviewed local override** | <1% (1) |
| — | **Unmatched** | 2% (10) |
| **Total** | | **98% geocoded (422/432 current resolved non-APS rows)** |

Street name normalization (uppercase, abbreviation expansion, whitespace collapse) is applied before all matching. Both orderings of street pairs are tried. Tier 3 results are validated against CB5 polygon bounds.

Results are cached to `output/geocode_cache_signal_studies.csv`. The cache is synchronized to the current resolved non-APS signal-study universe before reuse, so newly added current rows remain explicit unmatched rows if local geocoding cannot locate them. Current unmatched rows are also exported to `output/data_unmatched_signal_geocodes.csv` for manual review; these rows do not appear in the signal-study map layers or proximity statistics until they receive an in-polygon coordinate. Delete the cache to force a full re-geocoding pass.

### 6.2 Proximity Analysis

For each safety request location, injury crashes within **150 meters** are counted. This radius is the standard for NYC Vision Zero intersection safety analysis (~1.5 blocks).

Four metrics are computed per location: `crashes_150m` (total injury crashes within 150m), `injuries_150m` (total persons injured), `ped_injuries_150m` (pedestrian injuries specifically), and `fatalities_150m` (fatalities). Distances are calculated using the Haversine formula (great-circle distance), vectorized for performance.

The crash dataset contains injury or fatal crashes (fetched with `number_of_persons_injured > 0 OR number_of_persons_killed > 0`); zero-injury, non-fatal crashes are excluded. This means the proximity analysis measures locations where people were hurt or killed, not all reported collisions.

### 6.3 Statistical Testing

Denied and approved location crash distributions are compared using the **Mann-Whitney U test** (non-parametric, does not assume normal distribution). Implementation is manual (no scipy dependency) using a normal approximation for p-values with tied-rank variance correction.

### Chart 09: Crash Proximity Analysis

Chart 09 (`chart_09_crash_proximity_analysis.png`) presents the central statistical test of this analysis. It displays grouped bars comparing denied and approved locations on three metrics — median crashes, injuries, and pedestrian injuries within 150 meters — with the Mann-Whitney U test p-value annotated on each panel. The current generated signal-study panel covers 422 geocoded Signal Study locations (380 denied, 42 approved), and the SRTS panel (`chart_09a_srts_crash_proximity.png`) covers 436 Speed Bump locations (430 denied, 6 approved).

For signal studies, denied locations have significantly more crashes than approved locations (median 15.0 for denied locations, 10.0 for approved locations, p=0.000743), a result that is statistically significant at the 1% level. Denied locations also show higher median injuries (21.0 for denied locations, 11.0 for approved locations) and higher median pedestrian injuries (3.0 for denied locations, 2.0 for approved locations). For SRTS, there is no statistically significant difference (median 12.0 for denied locations, 8.0 for approved locations, p=0.464641); this is consistent with the documented role of the radar-speed criterion in speed bump decisions.

This is the central statistical finding of the analysis. Within the geocoded signal-study subset, denied signal and stop sign locations have higher nearby injury-crash counts than approved locations (Mann-Whitney p=0.000743). This supports further review of whether approval criteria are prioritizing documented crash exposure. It does not by itself prove causation or show DOT intent, and p-values are not the probability that a result is "due to chance." The non-significant SRTS result is consistent with the documented role of radar speed in speed bump decisions, but it does not prove that crash history is ignored in every decision.

### Chart 09b: Top 15 Denied Locations in QCB5 by Nearby Crash/Injury Count

Chart 09b (`chart_09b_denied_locations_crash_ranking.png`) identifies the denied signal study locations surrounded by the most crashes in a horizontal bar chart for QCB5, 2020–2025, paired with Chart 09c (`chart_09c_denied_locations_injury_ranking.png`) for injuries. **SRTS locations are excluded** because their segment-based coordinates create methodological issues with 150m overlap analysis, and speed bumps lack cross-street data needed for intersection-level precision. Street names are abbreviated for readability (Avenue→Ave, Street→St, Road→Rd, Boulevard→Blvd, Turnpike→Tpke, Place→Pl).

Three layers of de-duplication are applied before ranking. First, `_normalize_intersection()` sorts street names alphabetically so that "Cooper Ave & Cypress Ave" and "Cypress Ave & Cooper Ave" are treated as the same location. Second, a name-based groupby aggregates records sharing the same normalized intersection name, keeping the row with the highest crash count. Third, `_spatial_dedup(df, radius_m=150)` applies a greedy algorithm: locations are sorted by crashes descending, and any location within 150 meters (haversine distance) of an already-selected location is skipped. The 150-meter spatial dedup radius matches the analysis radius because two denied locations 100 meters apart would share most of the same crash pool, creating the appearance of distinct hotspots when the crash exposure is largely the same.

In the current committed snapshot (`table_09c_top_denied_by_crashes.csv`), the top denied intersection is Borden Avenue & Maurice Avenue (`CQ21-1110B`), with 120 crashes, 188 injuries, and 4 fatalities within 150 meters; Aubrey Avenue & Metropolitan Avenue (`CQ21-2789B`) ranks fourth with 70 crashes and 105 injuries. These are specific, nameable locations with denied requests and documented nearby crash exposure.

### Chart 15: SRTS Approval Funnel

Chart 15 (`chart_15_srts_funnel.png`) traces the full lifecycle of 255 QCB5 speed bump approvals from 1999–2025 in a two-panel layout. The left panel shows the total approved count, while the right panel breaks down their fate: Confirmed Installed at 110 (43.1%), Cancelled/Rejected at 134 (52.5%), Closed Without Install at 1 (0.4%), and Still Waiting at 10 (3.9%), with the median wait time annotated on the Still Waiting bar. Cancellation is determined from the `projectstatus` field containing "Cancel," "Reject," or "denied" — DOT's own status labels, not this analysis's classification. SRTS data is loaded via `_load_cb5_srts_full()` with the full CB5 filtering pipeline.

This is the full lifecycle view of an SRTS approval. The current output shows that 43.1% of approvals result in confirmed installation, while 52.9% are later cancelled, rejected, or closed without installation, and 3.9% remain open. A "yes" from DOT therefore overstates actual infrastructure delivery.

---

## 7. Interactive Map

### Map 02: Interactive Safety Infrastructure Explorer (Canonical)

- **Files:** `map_02_interactive_explorer.html` (approx. 50 KB shell) + external versioned `map_data.json` (1.6 MB). Legacy 17 MB Folium overlay output has been retired.
- **Base tiles:** CARTO Positron (`light_all`) and Dark Matter (`dark_all`), switching automatically with Electoral Analytics light/dark color scheme.
- **Typography & controls:** IBM Plex Sans / Spectral / IBM Plex Mono; collapsible controls rail with 2020–2025 default year filter, reference-number search, layer toggles, and verified SHA-384 CDN integrity hashes.

### 7.1 Map Layers

All layers share the same 2020–2025 analysis window. Layer names in the control panel include n= counts and year ranges.

| # | Layer | Default | n= | Description |
|---|-------|---------|-----|-------------|
| 1 | Injury Crashes | ON | 4,274 | Dot density — one dot per crash, sized by severity (fatal=black r=3.5, injury=gray r=1.8, property=light gray r=1.2) |
| 2 | Denied Signal Studies | ON | 380 | Red circle markers (r=6), signal/stop sign requests denied by DOT |
| 3 | Approved Signal Studies | ON | 42 | Green circle markers (r=6), signal/stop sign requests approved |
| 4 | Denied Speed Bumps | ON | 430 | Red circle markers (r=4), SRTS requests denied |
| 5 | Approved Speed Bumps | ON | 6 | Green circle markers (r=4), SRTS requests approved |
| 6 | DOT Effectiveness (Installed) | OFF | 15 | Before-after analysis markers — green (crashes decreased), amber (increased), gray (no change). Marker radius scaled by data volume. |
| 7 | Top 15 Denied Spotlight | OFF | 15 | Highest crash-surrounded denied locations with 150m analysis circles and rank labels (spatially de-duplicated at 150m) |

### 7.2 Popup Content

Every marker on the map provides rich data on click. This ensures that anyone exploring the map can drill into the specifics of any point.

**Crash dots:** Date, time, location (streets), severity tag (FATAL/INJURY), full injury breakdown (pedestrian/cyclist/motorist injured and killed), contributing factor, vehicle type, collision ID.

**Signal studies:** Reference number, request type, date requested, status date, full status description, outcome (color-coded), school name (if applicable), Vision Zero flag, findings, and nearby crash metrics (crashes, injuries, ped injuries, fatalities within 150m).

**Speed bumps:** Project code, street segment (on/from/to), request date, project status, denial reason (if denied), installation date (if installed), traffic direction, and nearby crash metrics within 150m.

**DOT Effectiveness:** Reference number, request type, date requested, install date, before-after crash comparison with percent change, injury comparison, analysis window duration.

**Top 15 Spotlight:** Rank, location name, source dataset (Signal Study or SRTS), request type, and full crash metrics within 150m (crashes, injuries, ped injuries, fatalities).

### 7.3 Layer Data Spreadsheets

Each map layer exports a corresponding CSV spreadsheet to `output/`. These allow users to examine, sort, and filter the underlying data for any layer they see on the map.

| File | Rows | Key Columns |
|------|------|-------------|
| `map_layer_crashes.csv` | 4,274 | date, time, streets, injury breakdown, contributing factor, vehicle type, collision ID, lat/lon |
| `map_layer_denied_signals.csv` | 380 | ref#, type, dates, status, findings, school, Vision Zero, crash proximity metrics, lat/lon |
| `map_layer_approved_signals.csv` | 42 | same as above |
| `map_layer_denied_speed_bumps.csv` | 430 | project code, streets, dates, denial reason, project status, crash proximity, lat/lon |
| `map_layer_approved_speed_bumps.csv` | 6 | same as above + install date |
| `map_layer_top15_denied.csv` | 15 | location, dataset, request type, crash/injury/ped/fatality counts |
| `table_before_after_installed.csv` | 15 | before-after crash/injury comparison per installed location |

### 7.4 Before-After Crash Analysis (Layer 6)

For the 15 confirmed-installed signal study locations, a before-after analysis compares crash counts in equal time windows before and after the installation date.

**Method:**
1. For each installed location, compute `months_before = install_date - 2020-01-01` and `months_after = 2025-12-31 - install_date`.
2. The analysis window is `min(months_before, months_after, 24)` — ensuring equal-length comparison periods, capped at 24 months.
3. Count all injury crashes within 150m of the installation point in the before and after windows.

**Aggregate result:** 63 crashes before → 58 after (-8%). 79 injuries before → 62 after (-21.5%).

**Standout wins:** Bleecker & Woodward (-86% crashes), Linden & Onderdonk (-50%), Seneca & Weirfield (-20%).

**Interpretation note:** Across installed locations, before/after injury counts decline by 21.5% in this descriptive analysis. That pattern is consistent with safety benefits but is not, by itself, a causal estimate; it should be read as supporting context for reviewing approved projects that have not yet been confirmed installed.

---

## 8. De-Duplication (Chart 06)

During review, administrative duplicates were identified. Specifically, 5 records at Metropolitan Ave & Flushing Ave from the same date (2022-09-06) shared a single external reference number (DOT-563803-L0J5) with empty study data fields.

**Method:** Records sharing the same DOT external reference number are collapsed to one record per unique reference, retaining the most recent `statusdate`. Records with null or non-DOT external references are kept as-is.

**Impact:** 7 records collapsed (445 → 438 unique). Applied only to Chart 06 (intersection-level counting), not to aggregate charts where the impact is negligible (<1.6%).

---

## 9. Speed Bump Denial Reason Classification

The `denialreason` field in SRTS data is free-text. Categories:

| Category | Matching Logic |
|----------|---------------|
| Speed < 30 mph | Contains "speed" AND ("below" OR "radar") |
| Driveways | Contains "driveway" or "curb cut" |
| Street Too Short | Contains "street too short" or "block" |
| Stop Controls | Contains "stop control" |
| Bus Route | Contains "bus" |
| Near Speed Camera | Contains "camera" |
| Not Specified | Null/empty denial reason |
| Other | All remaining reasons |

**Key finding:** "Speed < 30 mph" accounts for 84% of CB5 speed bump denials in 2020–2025, up from 37% across the full history. This single criterion has become the overwhelmingly dominant reason for denial.

---

## 10. Visual Style

All visualizations follow the conventions documented in `~/sites/electoralanalytics-site/docs/style/dataviz.md`. Key rules:

- **QCB5 = navy blue `#2C5F8B`** everywhere. Citywide = goldenrod `#B8860B` everywhere.
- **Denied = muted red `#B44040`**. Approved = muted green `#4A7C59`.
- Every chart title includes: specific year range (YYYY–YYYY, en-dash), sample size (n=), and QCB5 shorthand.
- Main charts use 2020–2025. Z-series use actual year ranges, capped at 2025.
- Maps use Times New Roman; charts use system serif.

---

## 11. Code Architecture

The analysis is structured as a two-part pipeline:

```
scripts_fetch_data.py          → data_raw/*.csv (raw API downloads)
generate_charts.py  (Part 1)   → output/chart_01–08, 12*.png + tables
generate_maps.py    (Part 2)   → output/map_01*.html + chart_09, 09b, 15*.png + tables + layer CSVs
```

Both scripts share identical patterns: outcome classification, APS exclusion, polygon filtering, and street name normalization. The `_normalize_street_name()` function exists in both files to avoid cross-file imports.

Each chart function is self-contained: it loads its data, computes its metrics, generates its visualization, and saves both the chart and its underlying data table. This ensures any single chart can be regenerated independently.

### 11.1 Shared Helper Functions (generate_maps.py)

| Function | Purpose |
|----------|---------|
| `_load_cb5_srts_full()` | Centralized SRTS loader applying full CB5 pipeline (cb=405 + polygon filter). Used by chart 15 and map layers. |
| `_normalize_intersection(a, b)` | Alphabetically sort two street names to prevent reversed-name duplicates ("A & B" == "B & A"). |
| `_spatial_dedup(df, radius_m)` | Greedy spatial de-duplication: sort by crashes desc, skip entries within `radius_m` (haversine) of already-selected locations. |
| `_filter_points_in_cb5(df)` | Polygon filter against official CB5 boundary. Excludes rows without coordinates. |
| `_normalize_street_name(s)` | Uppercase, expand abbreviations (AVE→AVENUE, ST→STREET, etc.), collapse whitespace. Exists in both scripts. |

---

## 12. Reproducibility

```bash
source .venv/bin/activate
python scripts_fetch_data.py   # Fetch fresh data (may change results)
python generate_charts.py      # Part 1: all charts
python generate_maps.py        # Part 2: map + correlation charts
```

**Note:** Re-fetching data will produce different results as the NYC Open Data API reflects ongoing updates to city records. The current committed raw snapshot is preserved in `data_raw/` and validated by `scripts_validate_outputs.py`; live refreshes should be reviewed before replacing those files.

---

## 13. Data Integrity Audit Log

### 13.1 Audit: Feb 13, 2026

A comprehensive data integrity audit was conducted across all charts and data pipelines. The audit was triggered by suspicious patterns in Chart 09b (clusters of identical crash counts, apparent duplicate locations).

**Bugs found and fixed:**

| # | Bug | Impact | Fix |
|---|-----|--------|-----|
| 1 | **`_filter_points_in_cb5()` included no-coordinate rows** | Crash count inflated from 3,213 to 3,938 (+725). No-coord rows had NaN lat/lon so did not affect proximity analysis, but inflated n= in chart titles (Chart 08, map layer counts). | Exclude rows without valid coordinates. Applied in both `generate_charts.py` and `generate_maps.py`. |
| 2 | **Charts 13 (now 01d), 15 loaded SRTS without full CB5 filtering** | These charts loaded SRTS directly from CSV with only `cb=405`, missing polygon filter. Current data has 27 resolved records outside the actual CB5 boundary after the `cb=405` filter. Current filtered output reports 239 feasible SRTS approvals and 105 confirmed installations. | Created `_load_cb5_srts_full()` shared helper. Chart 01d (formerly 13) moved to `generate_charts.py` using the shared `prepare_data()` pipeline. Chart 15 refactored to use `_load_cb5_srts_full()`. |
| 3 | **Chart 06 missing year filter** | Title claimed "2020–2025" but no year filter was applied. Included all-years data in a chart labeled as 2020–2025. | Added explicit `.between(2020, 2025)` year filter. |
| 4 | **Chart 09b reversed intersection duplicates** | "Cooper Ave & Cypress Ave" and "Cypress Ave & Cooper Ave" treated as different locations. | Created `_normalize_intersection()` to sort street names alphabetically. |
| 5 | **Chart 09b spatial duplicates from overlapping 150m radii** | Nearby denied locations (e.g., same intersection in Signal Studies and SRTS) counted overlapping crash pools, appearing as separate hotspots. | Created `_spatial_dedup()` with 150m radius matching the analysis radius. Applied to chart 09b, map Top 15 spotlight, and table_09c. |
| 6 | **Chart 09b right panel not independently sorted** | Right panel (injuries) used left panel's crash-count sort order instead of sorting independently by injury count. | Each panel now independently selects and sorts its own top 15. |

**Data verified as correct:**
- Crash uniqueness: 4,274 injury and fatal crash rows in the current 2020–2025 CB5 polygon snapshot with unique `collision_id` values — no source-level duplication.
- CB5 polygon bounds verified: lat 40.6823–40.7351, lon -73.9245 to -73.8553.
- Proximity methodology sound: nearby crash counts (such as 120 crashes within 150m of Borden Ave & Maurice Ave, and 70 near Aubrey Ave & Metropolitan Ave) represent distinct collision events within 150m.
- Multiple crashes share exact intersection coordinates over time — expected behavior for repeated collisions at the same intersection.

**Documentation errors that contributed to bugs:**
- `AGENTS.md` / README CB5 identification notes once listed only `cb='405'` for SRTS without mentioning mandatory polygon filter — this omission led to charts being built without proper filtering.
- Earlier project notes documented independent SRTS loading from CSV as intentional design rather than identifying it as inconsistent with the centralized pipeline.
- `METHODOLOGY.md` section 3.3 described independent loading as deliberate behavior.
- Chart 13 (denied and approved counts) was renumbered to Chart 01d and moved from `generate_maps.py` to `generate_charts.py`, with both panels aligned to 2020–2025. The previous version had mismatched date ranges (signals 2020–2025, SRTS 1999–2025).

All documentation updated to prevent recurrence.

---

## 14. Summary of Key Findings

1. **QCB5's signal study denial rate is ~90%** (2020–2025), consistent with the citywide average of ~88%. This is not a local anomaly in the current snapshot; high denial rates appear across boroughs.

2. **QCB5's speed bump denial rate has reached 99–100%** in recent years, with "Speed < 30 mph" recorded as the dominant denial reason.

3. **Denied signal study locations have significantly more nearby crashes than approved locations** in the geocoded subset (median 15.0 for denied locations, 10.0 for approved locations, Mann-Whitney p=0.000743). This is evidence that approval criteria should be reviewed against documented crash exposure; it is not, by itself, proof of causation or intent.

4. **Only 3.6% of signal study requests and 5.7% of speed bump requests result in confirmed installations.** Approval counts overstate confirmed infrastructure delivery by roughly 2x.

5. **26 of 41 approved signal studies (after dedup) have no installation date.** The 15 confirmed installations had a maximum wait of 456 days; 24 of the 26 uninstalled approvals have been waiting longer.

6. **For SRTS, more approvals were cancelled after the fact (134) than were actually installed (110).** 10 locations remain open without installation.

7. **Across the 15 installed signal-study intersections with matched before-and-after windows (`table_before_after_installed.csv`), nearby crashes fell from 80 to 64 (-20.0%) and injuries fell from 99 to 69 (-30.3%).** Because this is a small uncontrolled before-and-after series (n=15) without a matched comparison group, it is descriptive and does not isolate regression to the mean or citywide crash trends.
