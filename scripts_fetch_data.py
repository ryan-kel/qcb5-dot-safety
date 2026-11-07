"""
Comprehensive NYC DOT Safety Data Explorer
==========================================
This script downloads and explores ALL relevant NYC Open Data datasets for
Community Board 5 (Queens) safety analysis.

Datasets:
1. Traffic Signal and All-Way Stop Study Requests (w76s-c5u4) - PRIMARY
2. Speed Reducer Tracking System / SRTS (9n6h-pt9g)
3. Accessible Pedestrian Signal Locations (de3m-c5p4) - INSTALLED APS
4. Motor Vehicle Collisions (h9gi-nx95)
5. 311 Service Requests - DOT subset (erm2-nwe9)
6. CB5 boundary GeoJSON cache (data_raw/cb5_boundary.geojson)

Author: CB5 Safety Analysis Project
"""

import pandas as pd
import requests
import os
import json
import sys
from datetime import datetime, timezone

# === CONFIGURATION ===
DATA_DIR = "data_raw"
OUTPUT_DIR = "output"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

CB5_BOUNDARY_PATH = f"{DATA_DIR}/cb5_boundary.geojson"
FETCH_PAGE_SIZE = 50000
FETCH_MANIFEST_PATH = f"{DATA_DIR}/fetch_manifest.json"
FETCH_ORDER_BY = {
    "signal_studies": "id",
    "srts": "projectcode",
    "aps_installed": "borocd, location, date_insta",
    "crashes": "collision_id",
    "311": "unique_key",
}

# NYC Open Data Socrata API endpoints
DATASETS = {
    "signal_studies": {
        "name": "Traffic Signal and All-Way Stop Study Requests",
        "endpoint": "w76s-c5u4",
        "description": "Primary dataset for infrastructure study requests (signals, stop signs, APS)",
        "doc_url": "https://data.cityofnewyork.us/Transportation/Traffic-Signal-and-All-Way-Stop-Study-Requests/w76s-c5u4",
    },
    "srts": {
        "name": "Speed Reducer Tracking System (SRTS)",
        "endpoint": "9n6h-pt9g",
        "description": "Speed bump/hump requests and their outcomes",
        "doc_url": "https://data.cityofnewyork.us/Transportation/Speed-Reducer-Tracking-System-SRTS-/9n6h-pt9g",
    },
    "aps_installed": {
        "name": "Accessible Pedestrian Signal Locations",
        "endpoint": "de3m-c5p4",
        "description": "Currently INSTALLED APS devices (not requests)",
        "doc_url": "https://data.cityofnewyork.us/Transportation/Accessible-Pedestrian-Signal-Locations/de3m-c5p4",
    },
    "crashes": {
        "name": "Motor Vehicle Collisions - Crashes",
        "endpoint": "h9gi-nx95",
        "description": "All motor vehicle crashes reported by NYPD",
        "doc_url": "https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95",
    },
    "cb_boundaries": {
        "name": "Community Board Boundaries",
        "endpoint": None,
        "description": "Cached CB5 boundary GeoJSON used for polygon filtering",
        "doc_url": "https://raw.githubusercontent.com/nycehs/NYC_geography/master/CD.geo.json",
    },
}

# We'll handle 311 separately due to size
DATASET_311 = {
    "name": "311 Service Requests (DOT)",
    "endpoint": "erm2-nwe9",
    "description": "311 complaints - maintenance focused, less reliable for new infrastructure",
    "doc_url": "https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9",
}


def new_fetch_manifest():
    """Create an empty manifest for a data refresh run."""
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "datasets": [],
    }


def fetch_view_metadata(endpoint):
    """Fetch compact metadata for a Socrata view."""
    metadata_url = f"https://data.cityofnewyork.us/api/views/{endpoint}.json"
    response = requests.get(metadata_url, timeout=30)
    response.raise_for_status()
    raw = response.json()
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "rowsUpdatedAt": raw.get("rowsUpdatedAt"),
        "viewLastModified": raw.get("viewLastModified"),
        "columns": [
            {
                "fieldName": col.get("fieldName"),
                "name": col.get("name"),
                "dataTypeName": col.get("dataTypeName"),
            }
            for col in raw.get("columns", [])
            if col.get("fieldName")
        ],
    }


def _append_fetch_manifest_entry(
    manifest,
    *,
    dataset_key,
    dataset_name,
    endpoint,
    doc_url,
    where,
    select,
    order,
    requested_limit,
    page_size,
    pages_fetched,
    rows_returned,
    output_path,
    metadata,
    error,
):
    if manifest is None:
        return
    manifest["datasets"].append({
        "key": dataset_key,
        "name": dataset_name,
        "endpoint": endpoint,
        "doc_url": doc_url,
        "resource_url": f"https://data.cityofnewyork.us/resource/{endpoint}.json",
        "fetched_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "where": where,
        "select": select,
        "order": order,
        "requested_limit": requested_limit,
        "page_size": page_size,
        "pages_fetched": pages_fetched,
        "rows_returned": rows_returned,
        "truncated_at_requested_limit": bool(requested_limit and rows_returned >= requested_limit),
        "output_path": output_path,
        "metadata": metadata or {},
        "success": error is None,
        "error": error,
    })


def write_fetch_manifest(manifest, path=FETCH_MANIFEST_PATH):
    """Write a fetch manifest to disk."""
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


def crash_fetch_where():
    """Build the CB5-area crash candidate query."""
    min_lon, min_lat, max_lon, max_lat = cb5_boundary_bbox()
    return (
        "crash_date >= '2020-01-01' "
        "AND latitude IS NOT NULL AND longitude IS NOT NULL "
        "AND (number_of_persons_injured > 0 OR number_of_persons_killed > 0) "
        f"AND latitude between {min_lat} and {max_lat} "
        f"AND longitude between {min_lon} and {max_lon}"
    )


def fetch_query_plan():
    """Return the planned Socrata query parameters for each live fetch."""
    return {
        "signal_studies": {
            "endpoint": DATASETS["signal_studies"]["endpoint"],
            "output_path": f"{DATA_DIR}/signal_studies_citywide.csv",
            "order": FETCH_ORDER_BY["signal_studies"],
        },
        "srts": {
            "endpoint": DATASETS["srts"]["endpoint"],
            "output_path": f"{DATA_DIR}/srts_citywide.csv",
            "order": FETCH_ORDER_BY["srts"],
        },
        "aps_installed": {
            "endpoint": DATASETS["aps_installed"]["endpoint"],
            "output_path": f"{DATA_DIR}/aps_installed_citywide.csv",
            "order": FETCH_ORDER_BY["aps_installed"],
        },
        "crashes": {
            "endpoint": DATASETS["crashes"]["endpoint"],
            "output_path": f"{DATA_DIR}/crashes_queens_2020plus.csv",
            "where": crash_fetch_where(),
            "limit": 50000,
            "order": FETCH_ORDER_BY["crashes"],
        },
        "311": {
            "endpoint": DATASET_311["endpoint"],
            "output_path": f"{DATA_DIR}/311_cb5_dot_2020plus.csv",
            "where": "agency='DOT' AND community_board='05 QUEENS' AND created_date >= '2020-01-01'",
            "limit": 50000,
            "order": FETCH_ORDER_BY["311"],
        },
    }


def fetch_dataset(
    endpoint,
    limit=None,
    where=None,
    select=None,
    order=None,
    *,
    page_size=FETCH_PAGE_SIZE,
    manifest=None,
    dataset_key=None,
    dataset_name=None,
    doc_url=None,
    output_path=None,
):
    """Fetch data from NYC Open Data Socrata API with pagination."""
    base_url = f"https://data.cityofnewyork.us/resource/{endpoint}.json"
    metadata = {}
    error = None
    records = []
    pages_fetched = 0

    try:
        try:
            metadata = fetch_view_metadata(endpoint)
        except Exception as e:
            print(f"  WARN metadata fetch failed for {endpoint}: {e}")

        offset = 0
        while True:
            remaining = None if limit is None else limit - len(records)
            if remaining is not None and remaining <= 0:
                break
            request_limit = page_size if remaining is None else min(page_size, remaining)
            params = {"$limit": request_limit, "$offset": offset}
            if where:
                params["$where"] = where
            if select:
                params["$select"] = select
            if order:
                params["$order"] = order

            response = requests.get(base_url, params=params, timeout=120)
            response.raise_for_status()
            page = response.json()
            if not page:
                break
            records.extend(page)
            pages_fetched += 1
            if len(page) < request_limit:
                break
            offset += len(page)
    except requests.HTTPError as e:
        status = response.status_code
        request_id = response.headers.get("X-Socrata-RequestId", "n/a")
        if status == 503 and "Site Currently Unavailable" in response.text[:500]:
            error = (
                f"  ERROR fetching {endpoint}: NYC Open Data/Socrata returned "
                f"'Site Currently Unavailable' (HTTP 503, request id {request_id})"
            )
            print(error)
        else:
            error = f"  ERROR fetching {endpoint}: HTTP {status} ({e}, request id {request_id})"
            print(error)
    except Exception as e:
        error = f"  ERROR fetching {endpoint}: {e}"
        print(error)

    df = pd.DataFrame(records)
    df.attrs["fetch_success"] = error is None
    df.attrs["fetch_error"] = error
    _append_fetch_manifest_entry(
        manifest,
        dataset_key=dataset_key or endpoint,
        dataset_name=dataset_name or endpoint,
        endpoint=endpoint,
        doc_url=doc_url,
        where=where,
        select=select,
        order=order,
        requested_limit=limit,
        page_size=page_size,
        pages_fetched=pages_fetched,
        rows_returned=len(df),
        output_path=output_path,
        metadata=metadata,
        error=error,
    )
    return df


def fetch_succeeded(df):
    """Return True when a fetch produced usable, complete data."""
    return not df.empty and df.attrs.get("fetch_success", True)


def _iter_coordinate_pairs(coords):
    """Yield lon/lat pairs from GeoJSON coordinate arrays."""
    if not coords:
        return
    first = coords[0]
    if isinstance(first, (int, float)):
        yield coords
        return
    for child in coords:
        yield from _iter_coordinate_pairs(child)


def cb5_boundary_bbox():
    """Return the CB5 boundary bounding box as min_lon, min_lat, max_lon, max_lat."""
    with open(CB5_BOUNDARY_PATH) as f:
        geojson = json.load(f)

    lons, lats = [], []
    for feature in geojson.get("features", []):
        for lon, lat, *_ in _iter_coordinate_pairs(feature.get("geometry", {}).get("coordinates", [])):
            lons.append(float(lon))
            lats.append(float(lat))

    if not lons or not lats:
        raise ValueError(f"No coordinates found in {CB5_BOUNDARY_PATH}")

    return min(lons), min(lats), max(lons), max(lats)


def explore_dataframe(df, name, show_samples=3):
    """Generate comprehensive exploration of a dataframe."""
    print(f"\n{'='*70}")
    print(f"DATASET: {name}")
    print(f"{'='*70}")

    print(f"\n[SHAPE] {df.shape[0]:,} rows x {df.shape[1]} columns")

    print(f"\n[COLUMNS] ({len(df.columns)} total):")
    for i, col in enumerate(df.columns):
        dtype = df[col].dtype
        non_null = df[col].notna().sum()
        pct = (non_null / len(df)) * 100 if len(df) > 0 else 0
        print(f"  {i+1:2}. {col:<40} {str(dtype):<15} {non_null:>6,} non-null ({pct:.0f}%)")

    print(f"\n[SAMPLE DATA] (first {show_samples} rows):")
    if not df.empty:
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', 50)
        print(df.head(show_samples).to_string())

    # Key categorical columns - show value counts
    print(f"\n[KEY FIELD DISTRIBUTIONS]:")
    categorical_hints = ['status', 'type', 'borough', 'description', 'category', 'reason']
    for col in df.columns:
        if any(hint in col.lower() for hint in categorical_hints):
            if df[col].dtype == 'object' and df[col].notna().sum() > 0:
                unique_count = df[col].nunique()
                if unique_count <= 30:  # Only show if reasonable number of categories
                    print(f"\n  >> {col} ({unique_count} unique values):")
                    vc = df[col].value_counts().head(15)
                    for val, count in vc.items():
                        pct = (count / len(df)) * 100
                        print(f"      {val:<50} {count:>6,} ({pct:>5.1f}%)")

    return df


def main():
    print("="*70)
    print("NYC DOT SAFETY DATA - COMPREHENSIVE EXPLORATION")
    print(f"Run Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    all_data = {}
    fetch_failures = []
    optional_fetch_failures = []
    fetch_manifest = new_fetch_manifest()
    fetch_queries = fetch_query_plan()

    def note_fetch_failure(label, required=True):
        if required:
            fetch_failures.append(label)
        else:
            optional_fetch_failures.append(label)
        print(f"  No fresh data returned for {label}; existing local CSV, if any, was left unchanged.")

    # =========================================================================
    # 1. SIGNAL STUDIES - Most important for denial analysis
    # =========================================================================
    print("\n\n" + "#"*70)
    print("# 1. TRAFFIC SIGNAL AND ALL-WAY STOP STUDY REQUESTS")
    print("#    This is your PRIMARY dataset for 'batting average' analysis")
    print("#"*70)
    print(f"\nDocumentation: {DATASETS['signal_studies']['doc_url']}")

    print("\nFetching CITYWIDE data (all boroughs, all time)...")
    df_studies = fetch_dataset(
        DATASETS['signal_studies']['endpoint'],
        manifest=fetch_manifest,
        dataset_key='signal_studies',
        dataset_name=DATASETS['signal_studies']['name'],
        doc_url=DATASETS['signal_studies']['doc_url'],
        output_path=fetch_queries['signal_studies']['output_path'],
        order=fetch_queries['signal_studies']['order'],
    )

    if fetch_succeeded(df_studies):
        # Save raw data
        df_studies.to_csv(f"{DATA_DIR}/signal_studies_citywide.csv", index=False)
        print(f"  Saved to {DATA_DIR}/signal_studies_citywide.csv")

        all_data['signal_studies'] = explore_dataframe(df_studies, "Signal Studies (Citywide)")

        # Queens breakdown
        print("\n[QUEENS BREAKDOWN]:")
        queens = df_studies[df_studies['borough'] == 'Queens']
        print(f"  Queens total: {len(queens):,} requests")
        if 'statusdescription' in queens.columns:
            print("\n  Queens Status Distribution:")
            for status, count in queens['statusdescription'].value_counts().items():
                pct = (count / len(queens)) * 100
                print(f"    {status:<55} {count:>5,} ({pct:>5.1f}%)")

        # Request type breakdown
        if 'requesttype' in df_studies.columns:
            print("\n[REQUEST TYPES - Citywide]:")
            for rtype, count in df_studies['requesttype'].value_counts().items():
                pct = (count / len(df_studies)) * 100
                print(f"    {rtype:<45} {count:>6,} ({pct:>5.1f}%)")
    else:
        note_fetch_failure(DATASETS['signal_studies']['name'])

    # =========================================================================
    # 2. SPEED REDUCER TRACKING SYSTEM (SRTS)
    # =========================================================================
    print("\n\n" + "#"*70)
    print("# 2. SPEED REDUCER TRACKING SYSTEM (SRTS)")
    print("#    Speed bump/hump requests - high denial rate dataset")
    print("#"*70)
    print(f"\nDocumentation: {DATASETS['srts']['doc_url']}")

    print("\nFetching CITYWIDE SRTS data...")
    df_srts = fetch_dataset(
        DATASETS['srts']['endpoint'],
        manifest=fetch_manifest,
        dataset_key='srts',
        dataset_name=DATASETS['srts']['name'],
        doc_url=DATASETS['srts']['doc_url'],
        output_path=fetch_queries['srts']['output_path'],
        order=fetch_queries['srts']['order'],
    )

    if fetch_succeeded(df_srts):
        df_srts.to_csv(f"{DATA_DIR}/srts_citywide.csv", index=False)
        print(f"  Saved to {DATA_DIR}/srts_citywide.csv")

        all_data['srts'] = explore_dataframe(df_srts, "Speed Reducer Tracking System")

        # CB5 breakdown (cb='405' for Queens CB5)
        if 'cb' in df_srts.columns:
            cb5_srts = df_srts[df_srts['cb'] == '405']
            print(f"\n[CB5 (Queens) SRTS]: {len(cb5_srts):,} requests")
            if 'segmentstatusdescription' in cb5_srts.columns and len(cb5_srts) > 0:
                print("  CB5 Status Breakdown:")
                for status, count in cb5_srts['segmentstatusdescription'].value_counts().items():
                    pct = (count / len(cb5_srts)) * 100
                    print(f"    {status:<45} {count:>5,} ({pct:>5.1f}%)")
    else:
        note_fetch_failure(DATASETS['srts']['name'])

    # =========================================================================
    # 3. ACCESSIBLE PEDESTRIAN SIGNALS - INSTALLED
    # =========================================================================
    print("\n\n" + "#"*70)
    print("# 3. ACCESSIBLE PEDESTRIAN SIGNAL (APS) LOCATIONS - INSTALLED")
    print("#    Note: This is INSTALLED signals, not requests")
    print("#    Requests are tracked in Signal Studies with requesttype='Accessible Pedestrian Signal'")
    print("#"*70)
    print(f"\nDocumentation: {DATASETS['aps_installed']['doc_url']}")

    print("\nFetching APS installed locations...")
    df_aps = fetch_dataset(
        DATASETS['aps_installed']['endpoint'],
        manifest=fetch_manifest,
        dataset_key='aps_installed',
        dataset_name=DATASETS['aps_installed']['name'],
        doc_url=DATASETS['aps_installed']['doc_url'],
        output_path=fetch_queries['aps_installed']['output_path'],
        order=fetch_queries['aps_installed']['order'],
    )

    if fetch_succeeded(df_aps):
        df_aps.to_csv(f"{DATA_DIR}/aps_installed_citywide.csv", index=False)
        print(f"  Saved to {DATA_DIR}/aps_installed_citywide.csv")

        all_data['aps_installed'] = explore_dataframe(df_aps, "APS Installed Locations")

        # Queens breakdown
        if 'borough' in df_aps.columns:
            queens_aps = df_aps[df_aps['borough'] == 'Queens']
            print(f"\n[QUEENS APS Installed]: {len(queens_aps):,} signals")

            # Try to identify CB5 area (would need spatial join ideally)
            if 'borocd' in df_aps.columns:
                cb5_aps = df_aps[df_aps['borocd'] == '405']
                print(f"[CB5 APS Installed]: {len(cb5_aps):,} signals")
    else:
        note_fetch_failure(DATASETS['aps_installed']['name'])

    # =========================================================================
    # 4. MOTOR VEHICLE CRASHES
    # =========================================================================
    print("\n\n" + "#"*70)
    print("# 4. MOTOR VEHICLE COLLISIONS - CRASHES")
    print("#    For correlating denied requests with crash locations")
    print("#"*70)
    print(f"\nDocumentation: {DATASETS['crashes']['doc_url']}")

    # Fetch by CB5 bounding box, then downstream chart/map scripts apply the exact CB5
    # polygon filter. Do not pre-filter to borough='QUEENS': some in-polygon crash rows
    # have a blank borough field. Include fatal-only crashes as well as injury crashes.
    crash_where = fetch_queries['crashes']['where']
    print("\nFetching CB5-area crash candidates (2020+, injury or fatal)...")
    df_crashes = fetch_dataset(
        DATASETS['crashes']['endpoint'],
        where=crash_where,
        limit=fetch_queries['crashes']['limit'],
        manifest=fetch_manifest,
        dataset_key='crashes',
        dataset_name=DATASETS['crashes']['name'],
        doc_url=DATASETS['crashes']['doc_url'],
        output_path=fetch_queries['crashes']['output_path'],
        order=fetch_queries['crashes']['order'],
    )

    if fetch_succeeded(df_crashes):
        df_crashes.to_csv(f"{DATA_DIR}/crashes_queens_2020plus.csv", index=False)
        print(f"  Saved to {DATA_DIR}/crashes_queens_2020plus.csv")

        all_data['crashes'] = explore_dataframe(df_crashes, "Motor Vehicle Crashes (CB5-area candidates 2020+)")
    else:
        note_fetch_failure(DATASETS['crashes']['name'])

    # =========================================================================
    # 5. 311 REQUESTS - Sample for DOT
    # =========================================================================
    print("\n\n" + "#"*70)
    print("# 5. 311 SERVICE REQUESTS (DOT)")
    print("#    Maintenance-focused - use with caution for infrastructure analysis")
    print("#    This is a SAMPLE - full dataset is massive")
    print("#"*70)
    print(f"\nDocumentation: {DATASET_311['doc_url']}")

    # Get CB5 DOT 311 requests from 2020+
    print("\nFetching CB5 DOT 311 requests (2020+)...")
    df_311 = fetch_dataset(
        DATASET_311['endpoint'],
        where=fetch_queries['311']['where'],
        limit=fetch_queries['311']['limit'],
        manifest=fetch_manifest,
        dataset_key='311',
        dataset_name=DATASET_311['name'],
        doc_url=DATASET_311['doc_url'],
        output_path=fetch_queries['311']['output_path'],
        order=fetch_queries['311']['order'],
    )

    if fetch_succeeded(df_311):
        df_311.to_csv(f"{DATA_DIR}/311_cb5_dot_2020plus.csv", index=False)
        print(f"  Saved to {DATA_DIR}/311_cb5_dot_2020plus.csv")

        all_data['311'] = explore_dataframe(df_311, "311 Requests (CB5 DOT 2020+)")
    else:
        note_fetch_failure(DATASET_311['name'], required=False)

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n\n" + "="*70)
    print("DOWNLOAD SUMMARY")
    print("="*70)
    print(f"\nAll raw data saved to: {DATA_DIR}/")
    print("\nCurrent CSV files in data_raw:")
    for f in os.listdir(DATA_DIR):
        if f.endswith('.csv'):
            size = os.path.getsize(f"{DATA_DIR}/{f}") / (1024*1024)
            print(f"  - {f} ({size:.1f} MB)")

    print("\n" + "="*70)
    print("DOCUMENTATION LINKS")
    print("="*70)
    for key, info in DATASETS.items():
        print(f"\n{info['name']}:")
        print(f"  URL: {info['doc_url']}")
        print(f"  Description: {info['description']}")
    print(f"\n{DATASET_311['name']}:")
    print(f"  URL: {DATASET_311['doc_url']}")
    print(f"  Description: {DATASET_311['description']}")

    if fetch_failures or optional_fetch_failures:
        print("\n" + "="*70)
        print("FETCH FAILURES")
        print("="*70)
        if fetch_failures:
            print("The refresh did not complete. Existing CSV files were left in place for failed required datasets:")
            for label in fetch_failures:
                print(f"  - {label}")
        if optional_fetch_failures:
            print("Optional datasets did not refresh:")
            for label in optional_fetch_failures:
                print(f"  - {label}")
    if fetch_failures:
        write_fetch_manifest(fetch_manifest)
        print(f"\nFetch manifest saved to: {FETCH_MANIFEST_PATH}")
        sys.exit(1)

    write_fetch_manifest(fetch_manifest)
    print(f"\nFetch manifest saved to: {FETCH_MANIFEST_PATH}")

    return all_data


if __name__ == "__main__":
    data = main()
