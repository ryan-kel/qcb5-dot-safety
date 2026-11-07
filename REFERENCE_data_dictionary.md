# NYC DOT Safety Data - Data Dictionary

This document describes all datasets used in the CB5 safety infrastructure analysis.

---

## Quick Reference: Dataset URLs

| Dataset | NYC Open Data URL | Endpoint ID |
|---------|-------------------|-------------|
| Traffic Signal Studies | https://data.cityofnewyork.us/Transportation/Traffic-Signal-and-All-Way-Stop-Study-Requests/w76s-c5u4 | `w76s-c5u4` |
| Speed Reducer (SRTS) | https://data.cityofnewyork.us/Transportation/Speed-Reducer-Tracking-System-SRTS-/9n6h-pt9g | `9n6h-pt9g` |
| APS Installed | https://data.cityofnewyork.us/Transportation/Accessible-Pedestrian-Signal-Locations/de3m-c5p4 | `de3m-c5p4` |
| Motor Vehicle Crashes | https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95 | `h9gi-nx95` |
| 311 Service Requests | https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9 | `erm2-nwe9` |

---

## 1. Traffic Signal and All-Way Stop Study Requests

**Purpose**: Primary dataset for tracking formal infrastructure requests to NYC DOT for traffic signals, stop signs, APS, and related infrastructure.

**File**: `data_raw/signal_studies_citywide.csv`
**Records in current committed raw snapshot**: 75,339 citywide
**Time Range in current committed raw snapshot**: 1996 - 2026

### Key Fields

| Field | Description | Example Values |
|-------|-------------|----------------|
| `referencenumber` | Request identifier; not guaranteed unique in the committed raw snapshot because duplicate source rows exist | CQ25-3181, CM22-1234 |
| `daterequested` | Date request was submitted | 2025-10-06T00:00:00.000 |
| `statusdescription` | **CRITICAL** - Current outcome status | See status table below |
| `studystatus` | Open/Closed indicator | OPEN, CLOSED |
| `requesttype` | Type of infrastructure requested | Traffic Signal, All-Way Stop, APS |
| `borough` | Borough | Queens, Brooklyn, etc. |
| `mainstreet` | Primary street of intersection | METROPOLITAN AVENUE |
| `crossstreet1` | Cross street | 69 STREET |
| `crossstreet2` | Second cross street (if applicable) | |
| `schoolcrossing` | Near a school? | Yes, No |
| `schoolname` | Name of nearby school | P.S. 229 EMANUEL KAPLAN |
| `visionzero` | Vision Zero priority location? | Yes, No |

### Status Descriptions (statusdescription)

**DENIED statuses** (count as rejection):
| Status | Meaning |
|--------|---------|
| `Study Request Denial` | Rejected without full engineering study - did not meet preliminary criteria |
| `Engineering Study Completed (Signals Engineering)` | Study done, but NO approval given = implicit rejection |
| `Denial - Sent to Enhanced Intersection` | Rejected, referred elsewhere |

**APPROVED statuses** (count as success):
| Status | Meaning |
|--------|---------|
| `Signal Approval` | Traffic signal installation approved |
| `A/W Approval` | All-Way Stop approved |
| `L/T Approval` | Left Turn signal approved |
| `LPI Approval` | Leading Pedestrian Interval approved |
| `APS Ranking Completed; Awaiting Design` | APS approved, in installation queue |
| `APS Installed` | APS physically installed |

**PENDING statuses**:
| Status | Meaning |
|--------|---------|
| `Construction In-Progress; Study On-Hold` | Waiting for construction to complete |
| `Consultant Study In Progress / Under Review` | Still being evaluated |

### Request Types (requesttype)

| Type | Description | Citywide Count | Denial Rate |
|------|-------------|----------------|-------------|
| Traffic Signal | New traffic light | 29,736 | 85.4% |
| All-Way Stop | All-way stop sign at intersection | 22,270 | 86.2% |
| Accessible Pedestrian Signal | APS for visually impaired | 5,163 | 16.9%* |
| Left Turn Arrow/Signal | Dedicated left turn signal | 5,347 | 91.5% |
| Leading Pedestrian Interval | Head start for pedestrians | 2,496 | 89.2% |

*APS is tracked separately because installed APS inventory is not comparable to discretionary request outcomes in this analysis.

---

## 2. Speed Reducer Tracking System (SRTS)

**Purpose**: Tracks requests for speed bumps and speed humps/cushions.

**File**: `data_raw/srts_citywide.csv`
**Records in current committed raw snapshot**: 59,169 citywide
**Time Range in current committed raw snapshot**: 1990 - 2026

### Key Fields

| Field | Description | Example Values |
|-------|-------------|----------------|
| `projectcode` | Unique project ID | SR-20240212-31334 |
| `cb` | Community Board number | 405 (= Queens CB5) |
| `borough` | Borough | Queens |
| `segmentstatusdescription` | **CRITICAL** - Outcome | Not Feasible, Feasible |
| `denialreason` | Why request was denied | See denial reasons below |
| `onstreet` | Street where bump requested | 87 AVENUE |
| `fromstreet` / `tostreet` | Block boundaries | 144 STREET to 148 STREET |
| `speedcushion` | Whether the segment uses a bus-friendly speed cushion rather than a standard hump | Yes, No |
| `requestdate` | Date of original request | 2024-02-12 |
| `closeddate` | Date request was resolved | 2024-06-20 |

### Community Board Codes

Format: `[Borough Code][District Number]`
- Borough 1 = Manhattan
- Borough 2 = Bronx
- Borough 3 = Brooklyn
- Borough 4 = Queens
- Borough 5 = Staten Island

**CB5 Queens = 405**

### Denial Reasons (QCB5, 2020-2025)

| Reason | Count | Notes |
|--------|-------|-------|
| Speed < 30 mph | 364 | Speed not high enough |
| Other | 19 | Does not match a standard category |
| Not Specified | 17 | No denial reason recorded |
| Near Speed Camera | 16 | Near an automated enforcement location |
| Street Too Short | 11 | Not enough roadway |
| Driveways | 3 | Physical constraints from driveways / curb cuts |

---

## 3. Accessible Pedestrian Signal (APS) Locations

**Purpose**: Shows INSTALLED APS devices (not requests - those are in Signal Studies).

**File**: `data_raw/aps_installed_citywide.csv`
**Records in current committed raw snapshot**: 4,404 installed citywide

### Context

APS devices provide audible and vibrotactile signals to assist blind and low-vision pedestrians at crosswalks. Primary references: [remedial order PDF](https://dralegal.org/wp-content/uploads/2018/06/208_Remedial_Order_ACC.pdf), [NYC DOT APS program](https://www.nyc.gov/html/dot/html/infrastructure/accessiblepedsignals.shtml).

This analysis uses the installed-location inventory (`de3m-c5p4`) as a separate map and count layer. APS is excluded from discretionary denial-rate calculations because installed inventory is not comparable to signal-study request outcomes.

### Key Fields

| Field | Description |
|-------|-------------|
| `location` | Intersection description (e.g., "Nostrand Avenue and Prospect Place") |
| `borough` | Borough |
| `borocd` | Community district code (405 = CB5 Queens) |
| `date_insta` | Installation date |
| `point_x` / `point_y` | Coordinates |

### APS by Borough (Installed)

| Borough | Installed |
|---------|-----------|
| Brooklyn | 1,127 |
| Queens | 1,050 |
| Bronx | 855 |
| Manhattan | 776 |
| Staten Island | 596 |
| **CB5 Queens (`borocd=405`)** | **102** |

---

## 4. Motor Vehicle Collisions - Crashes

**Purpose**: All motor vehicle crashes reported by NYPD. Useful for correlating denied safety requests with actual crash locations.

**File**: `data_raw/crashes_queens_2020plus.csv`
**Records**: CB5-area bounding-box candidates, 2020+, with at least one injury or fatality. Downstream chart and map scripts apply the official CB5 polygon filter.

### Key Fields

| Field | Description |
|-------|-------------|
| `crash_date` | Date of crash |
| `borough` | Borough |
| `latitude` / `longitude` | Location |
| `on_street_name` | Street where crash occurred |
| `number_of_persons_injured` | Total injuries |
| `number_of_pedestrians_injured` | Pedestrian injuries |
| `number_of_cyclist_injured` | Cyclist injuries |
| `contributing_factor_vehicle_1` | Primary cause |

---

## 5. NYC 311 Service Requests (DOT)

**Purpose**: Maintenance-focused complaints (broken lights, missing signs). Less reliable for formal infrastructure requests.

**File**: `data_raw/311_cb5_dot_2020plus.csv`
**Records**: Optional live-fetch output for the CB5 DOT subset, 2020+. This file is gitignored and may be absent because it is not consumed by the current analysis pipeline.

### Why 311 is Less Reliable for This Analysis

The 311 system is primarily for **maintenance** issues:
- Broken traffic lights
- Street lights out
- Missing/damaged signs
- Pothole complaints

It does NOT reliably track **new infrastructure requests** like:
- New traffic signals
- New stop signs
- Speed bumps

For new infrastructure analysis, use the **Signal Studies** and **SRTS** datasets instead.

---

## CB5 Key Statistics Summary

**Note:** Generated tables in `output/` are the authoritative statistics for the current snapshot. The primary committed outputs use **2020–2025**. For the current `output/table_01d_denied_vs_approved.csv`, the headline resolved counts are 390 denied / 42 approved signal studies excluding APS, and 430 denied / 6 approved speed bump requests.

### Traffic Signals & Stop Signs: All-Time (from Signal Studies)

| Metric | CB5 | Citywide | Difference |
|--------|-----|----------|------------|
| Total Requests | Requires regeneration | 75,339 raw records | |
| Denial Rate | Use generated tables | Use generated tables | |
| Batting Average | Use generated tables | Use generated tables | |

### Speed Bumps: All-Time (from SRTS)

| Metric | CB5 | Queens | Citywide |
|--------|-----|--------|----------|
| Total Requests | 1,988 resolved in-polygon CB5 records | Use generated tables | 59,169 raw records |
| Denial Rate | Use generated tables | Use generated tables | Use generated tables |
| Batting Average | Use generated tables | Use generated tables | Use generated tables |

For 2020–2025, current generated output reports 430 denied and 6 approved QCB5 speed bump requests.

---

## How to Use This Data

### API Access

All datasets can be accessed via the Socrata API:

```
https://data.cityofnewyork.us/resource/{ENDPOINT_ID}.json
```

Example - get all Queens signal studies:
```bash
curl "https://data.cityofnewyork.us/resource/w76s-c5u4.json?\$where=borough='Queens'&\$limit=50000"
```

### Local Files

After running `scripts_fetch_data.py`, data is saved to:
- `data_raw/signal_studies_citywide.csv`
- `data_raw/srts_citywide.csv`
- `data_raw/aps_installed_citywide.csv`
- `data_raw/crashes_queens_2020plus.csv`
- `data_raw/311_cb5_dot_2020plus.csv` (gitignored; not consumed by chart/map generation)

---

## Additional Resources

- **Vision Zero View**: https://vzv.nyc/ - Interactive crash data map
- **NYC DOT Data Feeds**: https://www.nyc.gov/html/dot/html/about/datafeeds.shtml
- **NYC Open Data Portal**: https://opendata.cityofnewyork.us/
