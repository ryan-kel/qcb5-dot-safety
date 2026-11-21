"""
Map Generation & Crash-Denial Correlation Analysis for CB5
==========================================================
Part 2: Correlates crash locations with denied/approved safety request
locations. Produces interactive HTML maps (folium) and static charts
(matplotlib).

Usage:
    python generate_maps.py
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from shapely.geometry import shape, Point
from shapely.prepared import prep
import hashlib
import json
import warnings
import os
import math
import datetime
import shutil
from street_norm import (
    clean_whitespace,
    format_aps_location,
    format_nyc_intersection,
    format_nyc_street,
    format_school_name,
)

warnings.filterwarnings('ignore')

# === CONFIGURATION ===
DATA_DIR = "data_raw"
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Study window: 2020 through the last COMPLETE calendar year.
# The partial current year is excluded (auto-extends every Jan 1).
STUDY_START_YEAR = 2020
LAST_COMPLETE_YEAR = datetime.date.today().year - 1   # complete calendar years only; partial current year excluded

GEOCODE_CACHE_PATH = f"{OUTPUT_DIR}/geocode_cache_signal_studies.csv"
UNMATCHED_SIGNAL_GEOCODES_PATH = f"{OUTPUT_DIR}/data_unmatched_signal_geocodes.csv"
CB5_BOUNDARY_PATH = f"{DATA_DIR}/cb5_boundary.geojson"
CB5_BOUNDARY_URL = "https://raw.githubusercontent.com/nycehs/NYC_geography/master/CD.geo.json"

GEOCODE_CACHE_COLUMNS = [
    'referencenumber', 'mainstreet', 'crossstreet1', 'requesttype',
    'statusdescription', 'outcome', 'year',
    'daterequested', 'statusdate',
    'latitude', 'longitude',
    'geocode_tier', 'main_norm', 'cross_norm',
]

UNMATCHED_SIGNAL_GEOCODE_COLUMNS = [
    'referencenumber', 'mainstreet', 'crossstreet1', 'requesttype',
    'statusdescription', 'outcome', 'year',
    'daterequested', 'statusdate',
    'main_norm', 'cross_norm',
    'geocode_status', 'review_note',
]

# Proximity analysis radius in meters
PROXIMITY_RADIUS_M = 150

# Manual coordinate corrections for misplaced geocodes.
# Key: reference number, Value: (latitude, longitude)
# These override any cached or computed coordinates.
GEOCODE_OVERRIDES = {
    'CQ21-0722': (40.7024, -73.8749),  # 74 St & Myrtle Ave — interpolated from crash data
}

# Data bundle version (semantic versioning)
DATA_BUNDLE_VERSION = "1.0"

# CB5 center for map defaults
CB5_CENTER = [40.714, -73.889]
CB5_ZOOM = 14


def _strip_trailing_whitespace(path):
    """Normalize generated text output so repository whitespace checks stay useful."""
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(line.rstrip() + '\n' for line in lines)

# Color scheme — EA house palette (IBX choropleth + tokens.css)
COLORS = {
    'primary': '#1D4B73',
    'citywide': '#B5882B',
    'denied': '#A63A32',
    'approved': '#3E7B57',
    'crash': '#4E6B84',
    'crash_alt': '#94ADC4',
}

# Muted heatmap gradient — warm parchment tones for print
HEATMAP_GRADIENT = {
    0.2: '#f5f0e1', 0.4: '#e0cda9', 0.6: '#c9a96e',
    0.8: '#a07850', 1.0: '#7a4a2a',
}

# Global CSS for Times New Roman on all Leaflet UI elements
MAP_FONT_CSS = """
<style>
  .leaflet-popup-content, .leaflet-control-layers,
  .leaflet-tooltip, .map-legend, .map-title {
      font-family: 'Times New Roman', 'Liberation Serif', Georgia, serif !important;
  }
  .leaflet-popup-content { font-size: 12px; line-height: 1.5; }
  .leaflet-popup-content b { font-size: 13px; }

  /* --- Layer control styling --- */
  .leaflet-control-layers {
      background: rgba(255, 255, 255, 0.92) !important;
      border: 1px solid #bbb !important;
      border-radius: 4px !important;
      box-shadow: 0 1px 4px rgba(0,0,0,0.12) !important;
      padding: 0 !important;
  }
  .leaflet-control-layers-expanded {
      padding: 8px 12px 8px 10px !important;
  }
  .leaflet-control-layers-list { font-size: 11px; line-height: 1.7; }
  .leaflet-control-layers-list label { cursor: pointer; }
  .leaflet-control-layers-list label:hover { color: #2C5F8B; }
  .leaflet-control-layers-separator { border-color: #ddd !important; margin: 4px 0 !important; }

  /* Spotlight radius circles (dashed stroke) must not intercept clicks */
  .leaflet-overlay-pane path[stroke-dasharray] { pointer-events: none !important; }

  /* --- Mobile-responsive --- */
  @media (max-width: 600px) {
    /* Collapse layer control on mobile — show toggle icon instead */
    .leaflet-control-layers { max-width: 44px; overflow: hidden; }
    .leaflet-control-layers-expanded { max-width: 220px; overflow: visible; }
    .leaflet-control-layers-list { font-size: 10px; line-height: 1.6; }

    .map-legend {
      font-size: 10px !important; padding: 6px 8px !important;
      bottom: 10px !important; left: 10px !important; max-width: 160px;
    }
    .map-legend .legend-header { font-size: 11px !important; }
    .map-legend .legend-dot { width: 9px !important; height: 9px !important; }
    .map-title {
      font-size: 13px !important; padding: 5px 12px !important;
    }
    .map-title #map-dynamic-title { font-size: 13px !important; }
    .map-title #map-dynamic-subtitle { font-size: 9px !important; }
    #search-container { display: none !important; }
  }
</style>
"""


def _inject_map_css(m):
    """Inject Times New Roman CSS into a folium map."""
    m.get_root().html.add_child(folium.Element(MAP_FONT_CSS))


def _add_dynamic_title(m):
    """Add a dynamic title that updates based on which layer checkboxes are active."""
    _yr_range = f'{STUDY_START_YEAR}–{LAST_COMPLETE_YEAR}'
    html = '''<div class="map-title" id="map-title-container" style="position:fixed;top:10px;left:50%;
        transform:translateX(-50%);z-index:1000;background:rgba(255,255,255,0.92);
        padding:8px 20px;border:1px solid #666;
        font-family:'Times New Roman',Georgia,serif;text-align:center;">
        <div id="map-dynamic-title" style="font-size:15px;font-weight:bold;">Safety Request Outcomes: QCB5 (Queens Community Board 5)</div>
        <div id="map-dynamic-subtitle" style="font-size:11px;color:#555;margin-top:2px;">Signal Studies and Speed Bumps with Injury and Fatal Crashes (2020\u20132025)</div>
    </div>
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        // Shared: read active layers from checkboxes
        function getActiveLayers() {
            var checkboxes = document.querySelectorAll('.leaflet-control-layers-overlays label');
            var layers = {};
            checkboxes.forEach(function(label) {
                var cb = label.querySelector('input');
                var name = label.textContent.trim();
                layers[name] = cb && cb.checked;
            });
            return layers;
        }
        function isActive(layers, prefix) {
            for (var key in layers) {
                if (key.indexOf(prefix) === 0 && layers[key]) return true;
            }
            return false;
        }

        function updateTitle(layers) {
            var titleEl = document.getElementById('map-dynamic-title');
            var subtitleEl = document.getElementById('map-dynamic-subtitle');
            var spotlight = isActive(layers, 'Top 15 Denied');
            var effectiveness = isActive(layers, 'DOT Effectiveness');
            var crashTop10 = isActive(layers, 'Top 10 Crash');
            var signals = isActive(layers, 'Denied Signal') || isActive(layers, 'Approved Signal');
            var srts = isActive(layers, 'Denied Speed') || isActive(layers, 'Approved Speed');
            if (effectiveness) {
                titleEl.textContent = 'DOT Effectiveness: Crash Outcomes After Installation';
                subtitleEl.textContent = 'Before-After Analysis, Confirmed Installations, QCB5';
            } else if (crashTop10) {
                titleEl.textContent = 'Top 10 Crash Intersections: QCB5';
                subtitleEl.textContent = 'Highest Crash-Frequency Intersections (2020\u20132025)';
            } else if (spotlight) {
                titleEl.textContent = 'Top 15 Denied Locations by Nearby Crash Count';
                subtitleEl.textContent = '150m Analysis Radius, QCB5';
            } else if (signals && srts) {
                titleEl.textContent = 'Safety Request Outcomes: QCB5';
                subtitleEl.textContent = 'Signal Studies and Speed Bumps with Injury and Fatal Crashes (2020\u20132025)';
            } else if (signals) {
                titleEl.textContent = 'Signal Study Outcomes: QCB5';
                subtitleEl.textContent = 'Traffic Signal and Stop Sign Requests with Crash Data';
            } else if (srts) {
                titleEl.textContent = 'Speed Bump Requests with Injury and Fatal Crashes';
                subtitleEl.textContent = 'SRTS Program, QCB5';
            } else {
                titleEl.textContent = 'Safety Infrastructure Data: QCB5';
                subtitleEl.textContent = 'Use layer controls to explore';
            }
        }

        function updateLegend(layers) {
            var anyVisible = false;
            document.querySelectorAll('.legend-item').forEach(function(el) {
                var prefixes = el.getAttribute('data-layers').split(',');
                var show = prefixes.some(function(p) { return isActive(layers, p.trim()); });
                el.style.display = show ? 'block' : 'none';
                if (show) anyVisible = true;
            });
            var legend = document.getElementById('map-legend');
            if (legend) legend.style.display = anyVisible ? '' : 'none';
        }

        function onLayerChange() {
            var layers = getActiveLayers();
            updateTitle(layers);
            updateLegend(layers);
        }

        // Wait for Leaflet layer control to render, then attach listeners
        var observer = new MutationObserver(function(mutations, obs) {
            var overlays = document.querySelector('.leaflet-control-layers-overlays');
            if (overlays) {
                obs.disconnect();
                overlays.addEventListener('change', onLayerChange);
                overlays.addEventListener('click', function() {
                    setTimeout(onLayerChange, 50);
                });
                onLayerChange();
            }
        });
        observer.observe(document.body, {childList: true, subtree: true});
    });
    </script>'''
    html = html.replace('2020–2025', _yr_range)
    m.get_root().html.add_child(folium.Element(html))


def _add_search_box(m, search_entries):
    """Add a search-by-reference-number box to the map.

    search_entries: list of dicts with keys ref, lat, lon, label, type, outcome.
    """
    import json as _json
    index_json = _json.dumps({e['ref']: e for e in search_entries if e.get('ref')})
    html = f'''
    <div id="search-container" style="position:fixed;right:12px;z-index:1001;
        font-family:'Times New Roman',Georgia,serif;display:none;">
      <div style="background:rgba(255,255,255,0.95);border:1px solid #666;padding:6px 8px;
          border-radius:3px;box-shadow:0 1px 4px rgba(0,0,0,0.2);">
        <input id="ref-search" type="text" placeholder="Search ref # (e.g. CQ21-0722)"
          style="width:200px;padding:4px 6px;font-family:'Times New Roman',Georgia,serif;
          font-size:12px;border:1px solid #999;border-radius:2px;" autocomplete="off">
        <button id="ref-search-btn" style="padding:4px 8px;font-family:'Times New Roman',Georgia,serif;
          font-size:12px;cursor:pointer;border:1px solid #999;background:#f5f5f5;
          border-radius:2px;margin-left:2px;">Go</button>
        <div id="ref-search-msg" style="font-size:11px;margin-top:3px;color:#666;"></div>
        <div id="ref-search-dropdown" style="display:none;position:absolute;background:white;
          border:1px solid #ccc;max-height:180px;overflow-y:auto;width:270px;
          font-size:11px;z-index:1002;box-shadow:0 2px 6px rgba(0,0,0,0.15);"></div>
      </div>
    </div>
    <script>
    (function() {{
      var SEARCH_INDEX = {index_json};
      var allRefs = Object.keys(SEARCH_INDEX);
      var highlightLayer = null;
      var highlightTimeout = null;

      function getMap() {{
        var maps = [];
        document.querySelectorAll('.folium-map').forEach(function(el) {{
          if (el._leaflet_id) {{
            for (var k in window) {{
              if (window[k] instanceof L.Map) maps.push(window[k]);
            }}
          }}
        }});
        return maps[0] || null;
      }}

      function clearHighlight() {{
        if (highlightLayer) {{
          try {{ highlightLayer.remove(); }} catch(e) {{}}
          highlightLayer = null;
        }}
        if (highlightTimeout) {{ clearTimeout(highlightTimeout); highlightTimeout = null; }}
      }}

      function normalize(s) {{ return s.replace(/[-\\s]/g, '').toUpperCase(); }}

      function fuzzyFind(ref) {{
        // Exact match
        if (SEARCH_INDEX[ref]) return ref;
        // Normalized match
        var nq = normalize(ref);
        for (var i = 0; i < allRefs.length; i++) {{
          if (normalize(allRefs[i]) === nq) return allRefs[i];
        }}
        // Substring match on normalized keys
        for (var i = 0; i < allRefs.length; i++) {{
          if (normalize(allRefs[i]).indexOf(nq) >= 0) return allRefs[i];
        }}
        return null;
      }}

      function doSearch(ref) {{
        ref = ref.trim().toUpperCase();
        var msgEl = document.getElementById('ref-search-msg');
        var found = fuzzyFind(ref);
        if (!found) {{
          msgEl.style.color = '#B44040';
          msgEl.textContent = 'Not found: ' + ref;
          return;
        }}
        ref = found;
        var entry = SEARCH_INDEX[ref];
        document.getElementById('ref-search').value = ref;
        msgEl.style.color = '#4A7C59';
        msgEl.textContent = entry.label + ' (' + entry.outcome + ')';
        var map = getMap();
        if (!map) return;
        clearHighlight();
        map.setView([entry.lat, entry.lon], 17);
        // Pulsing highlight ring
        highlightLayer = L.layerGroup();
        var ring = L.circleMarker([entry.lat, entry.lon], {{
          radius: 18, color: '#B8860B', weight: 3, fill: false, opacity: 0.9
        }});
        ring.addTo(highlightLayer);
        var popup = L.popup({{offset: [0, -8]}}).setLatLng([entry.lat, entry.lon])
          .setContent('<div style="font-family:Times New Roman,serif;font-size:12px;">' +
            '<b>' + entry.label + '</b><br>' + entry.ref + '<br>' +
            'Type: ' + (entry.type || 'N/A') + '<br>' +
            'Outcome: <b>' + entry.outcome + '</b></div>');
        popup.addTo(highlightLayer);
        highlightLayer.addTo(map);
        // Pulse animation
        var grow = true;
        var pulseInt = setInterval(function() {{
          if (!highlightLayer) {{ clearInterval(pulseInt); return; }}
          ring.setRadius(grow ? 24 : 18);
          ring.setStyle({{opacity: grow ? 0.5 : 0.9}});
          grow = !grow;
        }}, 600);
        highlightTimeout = setTimeout(function() {{
          clearHighlight(); clearInterval(pulseInt);
        }}, 8000);
        map.once('click', function() {{ clearHighlight(); clearInterval(pulseInt); }});
      }}

      function showDropdown(query) {{
        var dd = document.getElementById('ref-search-dropdown');
        if (!query || query.length < 2) {{ dd.style.display = 'none'; return; }}
        var uq = query.toUpperCase();
        var nq = normalize(query);
        var matches = allRefs.filter(function(r) {{
          return r.indexOf(uq) >= 0 || normalize(r).indexOf(nq) >= 0;
        }}).slice(0, 10);
        if (matches.length === 0) {{ dd.style.display = 'none'; return; }}
        dd.innerHTML = '';
        matches.forEach(function(ref) {{
          var entry = SEARCH_INDEX[ref];
          var div = document.createElement('div');
          div.style.cssText = 'padding:4px 8px;cursor:pointer;border-bottom:1px solid #eee;';
          div.textContent = ref + ' — ' + (entry.label || '');
          div.onmouseover = function() {{ this.style.background = '#f0f0f0'; }};
          div.onmouseout = function() {{ this.style.background = 'white'; }};
          div.onclick = function() {{
            document.getElementById('ref-search').value = ref;
            dd.style.display = 'none';
            doSearch(ref);
          }};
          dd.appendChild(div);
        }});
        dd.style.display = 'block';
      }}

      document.addEventListener('DOMContentLoaded', function() {{
        var input = document.getElementById('ref-search');
        var btn = document.getElementById('ref-search-btn');
        btn.onclick = function() {{ doSearch(input.value); }};
        input.onkeyup = function(e) {{
          if (e.key === 'Enter') {{ doSearch(input.value); document.getElementById('ref-search-dropdown').style.display = 'none'; }}
          else showDropdown(input.value);
        }};
        document.addEventListener('click', function(e) {{
          if (!document.getElementById('search-container').contains(e.target))
            document.getElementById('ref-search-dropdown').style.display = 'none';
        }});
        // Position search box below layer control
        function positionSearch() {{
          var lc = document.querySelector('.leaflet-control-layers');
          var sc = document.getElementById('search-container');
          if (lc && sc) {{
            var rect = lc.getBoundingClientRect();
            sc.style.top = (rect.bottom + 6) + 'px';
            sc.style.display = 'block';
          }}
        }}
        var posObs = new MutationObserver(function(mutations, obs) {{
          if (document.querySelector('.leaflet-control-layers')) {{
            obs.disconnect();
            positionSearch();
          }}
        }});
        posObs.observe(document.body, {{childList: true, subtree: true}});
      }});
    }})();
    </script>'''
    m.get_root().html.add_child(folium.Element(html))


# Editorial styling — Option A Civic Broadsheet sans-serif (matches generate_charts.py)
plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['IBM Plex Sans', 'DejaVu Sans', 'Helvetica', 'Arial'],
    'font.size': 10.5,
    'text.color': '#132230',
    'axes.labelcolor': '#4D5E6D',
    'axes.edgecolor': '#BAC6D3',
    'axes.linewidth': 0.8,
    'axes.titlesize': 12.5,
    'axes.titleweight': 'bold',
    'axes.labelsize': 10.5,
    'axes.labelweight': 'bold',
    'axes.spines.top': False,
    'axes.spines.right': False,
    'xtick.labelsize': 9.5,
    'ytick.labelsize': 9.5,
    'xtick.color': '#4D5E6D',
    'ytick.color': '#4D5E6D',
    'legend.fontsize': 9.5,
    'legend.frameon': True,
    'legend.facecolor': '#FFFFFF',
    'legend.edgecolor': '#DCE2E8',
    'figure.dpi': 150,
    'savefig.dpi': 300,
    'axes.grid': True,
    'grid.color': '#DCE2E8',
    'grid.alpha': 0.7,
    'grid.linestyle': '--',
})


# ============================================================
# Data Loading & Preparation (mirrors generate_charts.py)
# ============================================================

def _classify_outcome(status):
    if pd.isna(status):
        return 'unknown'
    s = status.lower()
    if 'denial' in s or ('engineering study completed' in s and 'approval' not in s):
        return 'denied'
    if 'approval' in s or 'approved' in s or 'aps installed' in s or 'aps ranking' in s or 'aps design' in s:
        return 'approved'
    return 'pending'


def _normalize_street_name(name):
    """Normalize street names for matching: uppercase, expand abbreviations."""
    if pd.isna(name) or str(name).strip() == '':
        return ''
    s = str(name).strip().upper()
    # Remove extra whitespace
    s = ' '.join(s.split())
    # Expand common abbreviations at end of string
    abbrevs = {
        ' AVE': ' AVENUE', ' BLVD': ' BOULEVARD', ' RD': ' ROAD',
        ' ST': ' STREET', ' PL': ' PLACE', ' DR': ' DRIVE',
        ' LN': ' LANE', ' CT': ' COURT', ' PKWY': ' PARKWAY',
        ' TPKE': ' TURNPIKE', ' EXPWY': ' EXPRESSWAY',
    }
    for abbr, full in abbrevs.items():
        if s.endswith(abbr):
            s = s[:-len(abbr)] + full
    return s


def _sync_geocode_cache_with_current_records(cache, cb5_no_aps):
    """Align cached signal geocodes to the current resolved non-APS records."""
    current = cb5_no_aps.copy()
    cache = cache.copy()

    if 'main_norm' not in current.columns:
        current['main_norm'] = current['mainstreet'].apply(_normalize_street_name)
    if 'cross_norm' not in current.columns:
        current['cross_norm'] = current['crossstreet1'].apply(_normalize_street_name)

    for col in GEOCODE_CACHE_COLUMNS:
        if col not in current.columns:
            current[col] = np.nan
        if col not in cache.columns:
            cache[col] = np.nan

    current['_cache_occurrence'] = current.groupby('referencenumber', dropna=False).cumcount()
    cache['_cache_occurrence'] = cache.groupby('referencenumber', dropna=False).cumcount()

    cached_coords = cache[
        ['referencenumber', '_cache_occurrence', 'latitude', 'longitude', 'geocode_tier']
    ].copy()

    synced = current.drop(columns=['latitude', 'longitude', 'geocode_tier']).merge(
        cached_coords,
        on=['referencenumber', '_cache_occurrence'],
        how='left',
        sort=False,
    )
    synced['geocode_tier'] = synced['geocode_tier'].fillna('')

    return synced[GEOCODE_CACHE_COLUMNS].copy()


def _write_unmatched_signal_geocode_report(cache, path=UNMATCHED_SIGNAL_GEOCODES_PATH):
    """Write unresolved signal-study geocodes that need manual review."""
    unmatched = cache[cache['latitude'].isna() | cache['longitude'].isna()].copy()
    for column in ['main_norm', 'cross_norm']:
        source = 'mainstreet' if column == 'main_norm' else 'crossstreet1'
        if column not in unmatched.columns:
            unmatched[column] = unmatched[source].apply(_normalize_street_name)
        else:
            missing_norm = unmatched[column].isna() | (unmatched[column].astype(str).str.strip() == '')
            unmatched.loc[missing_norm, column] = unmatched.loc[missing_norm, source].apply(_normalize_street_name)

    report = unmatched.copy().reset_index(drop=True)
    report['geocode_status'] = 'unmatched'
    report['review_note'] = (
        'No in-polygon local match from crash intersection, SRTS endpoint, '
        'street-line intersection, or manual override tiers.'
    )
    for column in UNMATCHED_SIGNAL_GEOCODE_COLUMNS:
        if column not in report.columns:
            report[column] = ''
    report = report[UNMATCHED_SIGNAL_GEOCODE_COLUMNS]
    report.to_csv(path, index=False)
    return report


def _load_cb5_polygon():
    """Load the CB5 boundary as a shapely polygon for point-in-polygon tests.

    Downloads the GeoJSON from NYC geography GitHub repo if not cached locally.
    """
    geojson = _load_cb5_boundary()
    return shape(geojson['features'][0]['geometry'])


def _filter_points_in_cb5(df, lat_col='latitude', lon_col='longitude'):
    """Filter a DataFrame to only rows whose coordinates fall inside the CB5 polygon.

    Returns (filtered_df, n_excluded).
    """
    poly = _load_cb5_polygon()
    prepared = prep(poly)

    has_coords = df[lat_col].notna() & df[lon_col].notna()
    with_coords = df[has_coords]
    n_no_coords = (~has_coords).sum()

    inside = with_coords.apply(
        lambda r: prepared.contains(Point(r[lon_col], r[lat_col])), axis=1
    )
    filtered = with_coords[inside]
    n_excluded = (~inside).sum() + n_no_coords
    if n_no_coords > 0:
        print(f"    ({n_no_coords:,} rows without coordinates excluded)")
    return filtered, n_excluded


def _load_cb5_srts_full():
    """Load CB5 SRTS data with full filtering pipeline (all years).

    Applies: cb=405 → polygon filter (CB5 boundary polygon is sole authority).
    Returns all CB5 records (all statuses) with outcome column added
    (denied/approved for resolved, NaN for pending/other).
    """
    srts = pd.read_csv(f'{DATA_DIR}/srts_citywide.csv', low_memory=False)
    srts['cb_num'] = pd.to_numeric(srts['cb'], errors='coerce')
    srts['requestdate'] = pd.to_datetime(srts['requestdate'], errors='coerce')
    srts['year'] = srts['requestdate'].dt.year

    cb5_raw = srts[srts['cb_num'] == 405].copy()

    # Polygon filter: the CB5 boundary polygon is the sole authority.
    cb5_raw['fromlatitude'] = pd.to_numeric(cb5_raw['fromlatitude'], errors='coerce')
    cb5_raw['fromlongitude'] = pd.to_numeric(cb5_raw['fromlongitude'], errors='coerce')
    cb5, _ = _filter_points_in_cb5(cb5_raw, lat_col='fromlatitude', lon_col='fromlongitude')

    cb5['outcome'] = cb5['segmentstatusdescription'].map({
        'Not Feasible': 'denied', 'Feasible': 'approved'
    })
    return cb5


def load_and_prepare_data():
    """Load all datasets and apply standard filtering."""
    print("Loading datasets...")

    signal_studies = pd.read_csv(f'{DATA_DIR}/signal_studies_citywide.csv', low_memory=False)
    srts = pd.read_csv(f'{DATA_DIR}/srts_citywide.csv', low_memory=False)
    crashes = pd.read_csv(f'{DATA_DIR}/crashes_queens_2020plus.csv', low_memory=False)
    # Pre-filtered CB5 signal studies: Queens borough records filtered to CB5 boundary streets.
    # Curated input — not auto-generated — because signal studies lack a community board field.
    cb5_studies = pd.read_csv(f'{OUTPUT_DIR}/data_cb5_signal_studies.csv', low_memory=False)

    print(f"  Signal Studies: {len(signal_studies):,}")
    print(f"  SRTS: {len(srts):,}")
    print(f"  Crashes: {len(crashes):,}")
    print(f"  CB5 Studies: {len(cb5_studies):,}")

    # --- Signal studies ---
    cb5_studies['outcome'] = cb5_studies['statusdescription'].apply(_classify_outcome)
    cb5_studies['daterequested'] = pd.to_datetime(cb5_studies['daterequested'], errors='coerce')
    cb5_studies['year'] = cb5_studies['daterequested'].dt.year
    cb5_resolved = cb5_studies[cb5_studies['outcome'].isin(['denied', 'approved'])]
    cb5_no_aps = cb5_resolved[cb5_resolved['requesttype'] != 'Accessible Pedestrian Signal']

    # --- SRTS ---
    srts['cb_num'] = pd.to_numeric(srts['cb'], errors='coerce')
    srts['requestdate'] = pd.to_datetime(srts['requestdate'], errors='coerce')
    srts['year'] = srts['requestdate'].dt.year
    srts_resolved = srts[srts['segmentstatusdescription'].isin(['Not Feasible', 'Feasible'])]
    cb5_srts_raw = srts_resolved[srts_resolved['cb_num'] == 405]

    # Polygon filter: the CB5 boundary polygon is the sole authority for geographic filtering.
    cb5_srts = cb5_srts_raw.copy()
    cb5_srts['outcome'] = cb5_srts['segmentstatusdescription'].map({
        'Not Feasible': 'denied', 'Feasible': 'approved'
    })
    cb5_srts['fromlatitude'] = pd.to_numeric(cb5_srts['fromlatitude'], errors='coerce')
    cb5_srts['fromlongitude'] = pd.to_numeric(cb5_srts['fromlongitude'], errors='coerce')
    cb5_srts, n_srts_excluded = _filter_points_in_cb5(
        cb5_srts, lat_col='fromlatitude', lon_col='fromlongitude')
    print(f"  CB5 SRTS: {len(cb5_srts_raw):,} raw -> {len(cb5_srts):,} after polygon filter ({n_srts_excluded} excluded)")

    # Filter SRTS to the study window for consistency with signal studies and crashes
    n_before_year = len(cb5_srts)
    cb5_srts = cb5_srts[cb5_srts['year'].between(STUDY_START_YEAR, LAST_COMPLETE_YEAR)].copy()
    print(f"  CB5 SRTS: -> {len(cb5_srts):,} after {STUDY_START_YEAR}–{LAST_COMPLETE_YEAR} filter ({n_before_year - len(cb5_srts)} excluded)")

    # --- Crashes ---
    crashes['crash_date'] = pd.to_datetime(crashes['crash_date'], errors='coerce')
    crashes['year'] = crashes['crash_date'].dt.year
    crashes = crashes[crashes['year'].between(STUDY_START_YEAR, LAST_COMPLETE_YEAR)]
    crashes['latitude'] = pd.to_numeric(crashes['latitude'], errors='coerce')
    crashes['longitude'] = pd.to_numeric(crashes['longitude'], errors='coerce')
    crashes['number_of_persons_injured'] = pd.to_numeric(crashes['number_of_persons_injured'], errors='coerce').fillna(0)
    crashes['number_of_pedestrians_injured'] = pd.to_numeric(crashes['number_of_pedestrians_injured'], errors='coerce').fillna(0)
    crashes['number_of_persons_killed'] = pd.to_numeric(crashes['number_of_persons_killed'], errors='coerce').fillna(0)

    # Polygon filter: Crashes — use actual CB5 boundary, not bounding box
    cb5_crashes, n_crash_excluded = _filter_points_in_cb5(crashes)
    print(f"  CB5 Crashes: {len(cb5_crashes):,} (polygon filter, {n_crash_excluded} Queens crashes excluded)")

    return {
        'signal_studies': signal_studies,
        'cb5_studies': cb5_studies,
        'cb5_no_aps': cb5_no_aps,
        'srts': srts,
        'cb5_srts': cb5_srts,
        'crashes': crashes,
        'cb5_crashes': cb5_crashes,
    }


# ============================================================
# Step 1: Geocode Signal Study Intersections
# ============================================================

def _build_crash_location_lookup(crashes):
    """Build (street1, street2) -> (lat, lon) lookup from crash data.

    Crashes use on_street_name + off_street_name for intersection crashes.
    """
    df = crashes[
        crashes['on_street_name'].notna() &
        crashes['off_street_name'].notna() &
        crashes['latitude'].notna() &
        crashes['longitude'].notna()
    ].copy()

    df['street_a'] = df['on_street_name'].apply(_normalize_street_name)
    df['street_b'] = df['off_street_name'].apply(_normalize_street_name)
    df = df[(df['street_a'] != '') & (df['street_b'] != '')]

    # Canonical key: sorted pair
    def _sort_pair(row):
        a, b = sorted([row['street_a'], row['street_b']])
        return pd.Series({'key_a': a, 'key_b': b})

    keys = df.apply(_sort_pair, axis=1)
    df['key_a'] = keys['key_a']
    df['key_b'] = keys['key_b']

    lookup = df.groupby(['key_a', 'key_b']).agg(
        lat=('latitude', 'median'),
        lon=('longitude', 'median'),
        n=('latitude', 'count')
    ).reset_index()
    lookup.rename(columns={'key_a': 'street_a', 'key_b': 'street_b'}, inplace=True)
    return lookup


def _build_srts_location_lookup(srts, polygon=None):
    """Build (street1, street2) -> (lat, lon) lookup from SRTS segment endpoints."""
    df = srts[
        srts['fromlatitude'].notna() &
        srts['fromlongitude'].notna() &
        srts['tolatitude'].notna() &
        srts['tolongitude'].notna()
    ].copy()

    df['fromlatitude'] = pd.to_numeric(df['fromlatitude'], errors='coerce')
    df['fromlongitude'] = pd.to_numeric(df['fromlongitude'], errors='coerce')
    df['tolatitude'] = pd.to_numeric(df['tolatitude'], errors='coerce')
    df['tolongitude'] = pd.to_numeric(df['tolongitude'], errors='coerce')
    df = df[
        df['fromlatitude'].notna() & df['fromlongitude'].notna() &
        df['tolatitude'].notna() & df['tolongitude'].notna()
    ]

    results = {}

    def add_candidate(street_a, street_b, lat, lon):
        if not street_a or not street_b:
            return
        if polygon is not None and not polygon.covers(Point(float(lon), float(lat))):
            return
        key = tuple(sorted([street_a, street_b]))
        if key not in results:
            results[key] = (lat, lon)

    for _, row in df.iterrows():
        main = _normalize_street_name(row.get('onstreet', ''))
        from_st = _normalize_street_name(row.get('fromstreet', ''))
        to_st = _normalize_street_name(row.get('tostreet', ''))

        add_candidate(main, from_st, row['fromlatitude'], row['fromlongitude'])
        add_candidate(main, to_st, row['tolatitude'], row['tolongitude'])
    return results


def _build_street_lines(crash_lookup, srts_lookup):
    """Build per-street linear regression lines from all known points.

    Returns dict: street_name -> (slope, intercept) for lat=f(lon).
    """
    street_points = {}

    # From crash lookup
    for _, row in crash_lookup.iterrows():
        for street in [row['street_a'], row['street_b']]:
            if street not in street_points:
                street_points[street] = []
            street_points[street].append((row['lon'], row['lat']))

    # From SRTS lookup
    for (s1, s2), (lat, lon) in srts_lookup.items():
        for street in [s1, s2]:
            if street not in street_points:
                street_points[street] = []
            street_points[street].append((lon, lat))

    street_lines = {}
    for street, points in street_points.items():
        if len(points) < 2:
            continue
        lons = np.array([p[0] for p in points])
        lats = np.array([p[1] for p in points])

        # Simple linear regression: lat = slope * lon + intercept
        if np.std(lons) < 1e-8:
            continue  # vertical line, skip
        slope, intercept = np.polyfit(lons, lats, 1)
        street_lines[street] = (slope, intercept)

    return street_lines


def _intersect_lines(line1, line2):
    """Find intersection of two lines: lat = slope * lon + intercept.

    Returns (lat, lon) or None if parallel.
    """
    s1, i1 = line1
    s2, i2 = line2
    if abs(s1 - s2) < 1e-10:
        return None  # parallel
    lon = (i2 - i1) / (s1 - s2)
    lat = s1 * lon + i1
    return (lat, lon)


def geocode_signal_studies(data):
    """Geocode CB5 signal study intersections using local data.

    Three tiers:
    1. Crash data intersection matching
    2. SRTS data matching
    3. Street-line intersection estimation
    """
    cb5_no_aps = data['cb5_no_aps'].copy()
    cb5_poly = _load_cb5_polygon()
    prepared_poly = prep(cb5_poly)

    def _in_cb5(lat, lon):
        return prepared_poly.contains(Point(lon, lat))

    # Check cache — but re-validate against polygon
    if os.path.exists(GEOCODE_CACHE_PATH):
        print("  Loading geocode cache...")
        cache = pd.read_csv(GEOCODE_CACHE_PATH)
        n_cache_before = len(cache)
        cache = _sync_geocode_cache_with_current_records(cache, cb5_no_aps)
        if len(cache) != n_cache_before:
            print(f"  Synced geocode cache to current records: {n_cache_before} -> {len(cache)}")
        # Re-filter cached results against polygon (cache may predate polygon fix)
        has_coords = cache['latitude'].notna() & cache['longitude'].notna()
        if has_coords.any():
            inside = cache[has_coords].apply(
                lambda r: _in_cb5(r['latitude'], r['longitude']), axis=1)
            n_outside = (~inside).sum()
            if n_outside > 0:
                print(f"  Removing {n_outside} cached points outside CB5 polygon")
                cache.loc[has_coords & ~inside.reindex(cache.index, fill_value=True), ['latitude', 'longitude']] = np.nan
                cache.loc[has_coords & ~inside.reindex(cache.index, fill_value=True), 'geocode_tier'] = ''

        # Clear stale-tier geocodes (old interpolation methods) for re-processing
        stale_tiers = {'crash_interp_cb5', 'srts_interp_cb5', 'srts_cb5'}
        stale_mask = cache['geocode_tier'].isin(stale_tiers)
        if stale_mask.any():
            print(f"  Clearing {stale_mask.sum()} stale-tier geocodes for re-processing")
            cache.loc[stale_mask, ['latitude', 'longitude']] = np.nan
            cache.loc[stale_mask, 'geocode_tier'] = ''

        # Re-geocode any records that are now missing coordinates
        needs_geocode = cache['latitude'].isna()
        if needs_geocode.any():
            print(f"  Re-geocoding {needs_geocode.sum()} records...")
            # Ensure normalized street names exist
            if 'main_norm' not in cache.columns:
                cache['main_norm'] = cache['mainstreet'].apply(_normalize_street_name)
                cache['cross_norm'] = cache['crossstreet1'].apply(_normalize_street_name)
            crash_lookup = _build_crash_location_lookup(data['crashes'])
            srts_lookup = _build_srts_location_lookup(data['srts'], cb5_poly)
            crash_keys = {}
            for idx, row in crash_lookup.iterrows():
                key = tuple(sorted([row['street_a'], row['street_b']]))
                crash_keys[key] = (row['lat'], row['lon'])
            srts_keys = dict(srts_lookup)
            street_lines = _build_street_lines(crash_lookup, srts_lookup)

            re_t1 = re_t2 = re_t3 = 0
            for i in cache.index[needs_geocode]:
                main = cache.at[i, 'main_norm']
                cross = cache.at[i, 'cross_norm']
                if not main or not cross or pd.isna(main) or pd.isna(cross):
                    continue
                key = tuple(sorted([main, cross]))
                # Tier 1: crash match
                if key in crash_keys:
                    lat, lon = crash_keys[key]
                    if _in_cb5(lat, lon):
                        cache.at[i, 'latitude'] = lat
                        cache.at[i, 'longitude'] = lon
                        cache.at[i, 'geocode_tier'] = 'crash'
                        re_t1 += 1; continue
                # Tier 2: SRTS match
                if key in srts_keys:
                    lat, lon = srts_keys[key]
                    if _in_cb5(lat, lon):
                        cache.at[i, 'latitude'] = lat
                        cache.at[i, 'longitude'] = lon
                        cache.at[i, 'geocode_tier'] = 'srts'
                        re_t2 += 1; continue
                # Tier 3: street-line intersection
                if main in street_lines and cross in street_lines:
                    result = _intersect_lines(street_lines[main], street_lines[cross])
                    if result is not None:
                        lat, lon = result
                        if _in_cb5(lat, lon):
                            cache.at[i, 'latitude'] = lat
                            cache.at[i, 'longitude'] = lon
                            cache.at[i, 'geocode_tier'] = 'street_line'
                            re_t3 += 1
            print(f"    Re-geocoded: {re_t1} crash, {re_t2} SRTS, {re_t3} street-line")

        # Apply manual overrides
        for ref, (lat, lon) in GEOCODE_OVERRIDES.items():
            mask = cache['referencenumber'] == ref
            if mask.any():
                cache.loc[mask, ['latitude', 'longitude']] = [lat, lon]
                cache.loc[mask, 'geocode_tier'] = 'manual'
                print(f"  Override applied: {ref} → ({lat}, {lon})")

        cache.to_csv(GEOCODE_CACHE_PATH, index=False)
        unmatched = _write_unmatched_signal_geocode_report(cache)
        geocoded = cache['latitude'].notna().sum()
        print(f"  Cache: {len(cache)} records, {geocoded} geocoded ({geocoded/len(cache)*100:.0f}%)")
        print(f"  Unmatched signal geocodes: {len(unmatched)} records -> {UNMATCHED_SIGNAL_GEOCODES_PATH}")
        return cache

    print("  Geocoding signal study intersections...")

    # Normalize signal study street names
    cb5_no_aps['main_norm'] = cb5_no_aps['mainstreet'].apply(_normalize_street_name)
    cb5_no_aps['cross_norm'] = cb5_no_aps['crossstreet1'].apply(_normalize_street_name)

    # Build lookups
    print("    Building crash location lookup...")
    crash_lookup = _build_crash_location_lookup(data['crashes'])
    print(f"    Crash lookup: {len(crash_lookup)} unique intersection pairs")

    print("    Building SRTS location lookup...")
    srts_lookup = _build_srts_location_lookup(data['srts'], cb5_poly)
    print(f"    SRTS lookup: {len(srts_lookup)} unique intersection pairs")

    # Results arrays
    lats = np.full(len(cb5_no_aps), np.nan)
    lons = np.full(len(cb5_no_aps), np.nan)
    geo_tier = np.full(len(cb5_no_aps), '', dtype=object)

    # Tier 1: Crash data matching
    crash_keys = {}
    for idx, row in crash_lookup.iterrows():
        key = tuple(sorted([row['street_a'], row['street_b']]))
        crash_keys[key] = (row['lat'], row['lon'])

    tier1_count = 0
    for i, (_, row) in enumerate(cb5_no_aps.iterrows()):
        main = row['main_norm']
        cross = row['cross_norm']
        if not main or not cross:
            continue

        key = tuple(sorted([main, cross]))
        if key in crash_keys:
            lat, lon = crash_keys[key]
            if _in_cb5(lat, lon):
                lats[i] = lat
                lons[i] = lon
                geo_tier[i] = 'crash'
                tier1_count += 1

    print(f"    Tier 1 (crash match): {tier1_count}/{len(cb5_no_aps)} "
          f"({tier1_count/len(cb5_no_aps)*100:.0f}%)")

    # Tier 2: SRTS matching
    tier2_count = 0
    for i, (_, row) in enumerate(cb5_no_aps.iterrows()):
        if not np.isnan(lats[i]):
            continue
        main = row['main_norm']
        cross = row['cross_norm']
        if not main or not cross:
            continue

        key = tuple(sorted([main, cross]))
        if key in srts_lookup:
            lat, lon = srts_lookup[key]
            if _in_cb5(lat, lon):
                lats[i] = lat
                lons[i] = lon
                geo_tier[i] = 'srts'
                tier2_count += 1

    print(f"    Tier 2 (SRTS match): {tier2_count}/{len(cb5_no_aps)} "
          f"({tier2_count/len(cb5_no_aps)*100:.0f}%)")

    # Tier 3: Street-line intersection
    print("    Building street regression lines...")
    street_lines = _build_street_lines(crash_lookup, srts_lookup)
    print(f"    Street lines: {len(street_lines)} streets with regression lines")

    tier3_count = 0
    for i, (_, row) in enumerate(cb5_no_aps.iterrows()):
        if not np.isnan(lats[i]):
            continue
        main = row['main_norm']
        cross = row['cross_norm']
        if not main or not cross:
            continue
        if main not in street_lines or cross not in street_lines:
            continue

        result = _intersect_lines(street_lines[main], street_lines[cross])
        if result is None:
            continue
        lat, lon = result
        if _in_cb5(lat, lon):
            lats[i] = lat
            lons[i] = lon
            geo_tier[i] = 'street_line'
            tier3_count += 1

    print(f"    Tier 3 (street-line): {tier3_count}/{len(cb5_no_aps)} "
          f"({tier3_count/len(cb5_no_aps)*100:.0f}%)")

    total_geocoded = tier1_count + tier2_count + tier3_count
    print(f"    Total geocoded: {total_geocoded}/{len(cb5_no_aps)} "
          f"({total_geocoded/len(cb5_no_aps)*100:.0f}%)")

    # Build result DataFrame
    cb5_no_aps = cb5_no_aps.copy()
    cb5_no_aps['latitude'] = lats
    cb5_no_aps['longitude'] = lons
    cb5_no_aps['geocode_tier'] = geo_tier

    # Save cache
    cache_df = cb5_no_aps[[c for c in GEOCODE_CACHE_COLUMNS if c in cb5_no_aps.columns]].copy()
    cache_df.to_csv(GEOCODE_CACHE_PATH, index=False)
    unmatched = _write_unmatched_signal_geocode_report(cache_df)
    print(f"    Cache saved to {GEOCODE_CACHE_PATH}")
    print(f"    Unmatched signal geocodes: {len(unmatched)} records -> {UNMATCHED_SIGNAL_GEOCODES_PATH}")

    return cache_df


# ============================================================
# Step 2: Proximity Analysis (Haversine)
# ============================================================

def _haversine_m(lat1, lon1, lat2, lon2):
    """Haversine distance in meters between two points."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _haversine_vectorized(lat1, lon1, lat2_arr, lon2_arr):
    """Haversine distance from one point to arrays of points. Returns meters."""
    R = 6371000
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2_arr)
    dphi = np.radians(lat2_arr - lat1)
    dlam = np.radians(lon2_arr - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def compute_proximity(locations_df, crashes_df, radius_m=PROXIMITY_RADIUS_M):
    """For each location, count crashes/injuries within radius.

    locations_df must have 'latitude', 'longitude' columns.
    Returns DataFrame with added columns: crashes_150m, injuries_150m,
    ped_injuries_150m, fatalities_150m.
    """
    crash_lats = crashes_df['latitude'].values
    crash_lons = crashes_df['longitude'].values
    crash_injuries = crashes_df['number_of_persons_injured'].values
    crash_ped_injuries = crashes_df['number_of_pedestrians_injured'].values
    crash_fatalities = crashes_df['number_of_persons_killed'].values

    results = {
        'crashes_150m': [],
        'injuries_150m': [],
        'ped_injuries_150m': [],
        'fatalities_150m': [],
    }

    for _, row in locations_df.iterrows():
        lat = row['latitude']
        lon = row['longitude']

        if pd.isna(lat) or pd.isna(lon):
            for key in results:
                results[key].append(np.nan)
            continue

        dists = _haversine_vectorized(lat, lon, crash_lats, crash_lons)
        mask = dists <= radius_m

        results['crashes_150m'].append(mask.sum())
        results['injuries_150m'].append(crash_injuries[mask].sum())
        results['ped_injuries_150m'].append(crash_ped_injuries[mask].sum())
        results['fatalities_150m'].append(crash_fatalities[mask].sum())

    for key, vals in results.items():
        locations_df = locations_df.copy()
        locations_df[key] = vals

    return locations_df


def _mann_whitney_u(x, y):
    """Manual Mann-Whitney U test (no scipy dependency).

    Returns (U statistic, approximate two-sided p-value).
    """
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    x = x[~np.isnan(x)]
    y = y[~np.isnan(y)]

    n1 = len(x)
    n2 = len(y)
    if n1 == 0 or n2 == 0:
        return np.nan, np.nan

    # Rank all values together
    combined = np.concatenate([x, y])
    order = np.argsort(combined)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(combined) + 1, dtype=float)

    # Handle ties: average ranks for tied values and apply the standard
    # tie correction to the normal-approximation variance.
    sorted_combined = combined[order]
    tie_sum = 0
    i = 0
    while i < len(sorted_combined):
        j = i + 1
        while j < len(sorted_combined) and sorted_combined[j] == sorted_combined[i]:
            j += 1
        if j > i + 1:
            avg_rank = np.mean(ranks[order[i:j]])
            for k in range(i, j):
                ranks[order[k]] = avg_rank
            tie_count = j - i
            tie_sum += tie_count**3 - tie_count
        i = j

    R1 = ranks[:n1].sum()
    U1 = R1 - n1 * (n1 + 1) / 2

    # Normal approximation for p-value
    n = n1 + n2
    mu = n1 * n2 / 2
    tie_correction = tie_sum / (n * (n - 1)) if n > 1 else 0
    variance = n1 * n2 * ((n + 1) - tie_correction) / 12
    sigma = math.sqrt(variance) if variance > 0 else 0
    if sigma == 0:
        return U1, 1.0

    z = (U1 - mu) / sigma
    p_two = math.erfc(abs(z) / math.sqrt(2))

    return U1, min(p_two, 1.0)


def run_proximity_analysis(signal_geo, srts_df, cb5_crashes):
    """Run proximity analysis for both signal studies and SRTS."""
    print("\n  Computing proximity for signal studies...")
    signal_with_coords = signal_geo[signal_geo['latitude'].notna()].copy()
    signal_prox = compute_proximity(signal_with_coords, cb5_crashes)

    print("  Computing proximity for SRTS...")
    srts_with_coords = srts_df.copy()
    srts_with_coords['latitude'] = pd.to_numeric(srts_with_coords['fromlatitude'], errors='coerce')
    srts_with_coords['longitude'] = pd.to_numeric(srts_with_coords['fromlongitude'], errors='coerce')
    srts_with_coords = srts_with_coords[srts_with_coords['latitude'].notna()].copy()
    srts_prox = compute_proximity(srts_with_coords, cb5_crashes)

    return signal_prox, srts_prox


# ============================================================
# Step 3: Maps (Folium)
# ============================================================

def _make_legend_html(items):
    """Generate HTML for a dynamic map legend — items show/hide with layer toggles.

    items: list of (color, label, layer_prefixes_csv[, icon_style]) tuples.
        layer_prefixes_csv: comma-separated layer name prefixes for visibility.
        icon_style: 'dot' (default) or 'spotlight' (dot + dashed radius circle).
    """
    html = ('<div class="map-legend" id="map-legend" style="position:fixed;bottom:40px;left:18px;'
            'z-index:1000;background:white;padding:10px 14px;border:1px solid #666;'
            "font-family:'Times New Roman',Georgia,serif;font-size:12px;line-height:1.8;\">")
    html += ('<span class="legend-header" style="font-size:13px;font-weight:bold;'
             'border-bottom:1px solid #999;display:block;margin-bottom:4px;'
             'padding-bottom:2px;">Legend</span>')
    for item in items:
        color, label, layer_prefixes = item[0], item[1], item[2]
        icon_style = item[3] if len(item) > 3 else 'dot'
        if icon_style == 'spotlight':
            # Dot + dashed circle — matches map spotlight/radius markers
            icon = (f'<span class="legend-dot" style="display:inline-block;width:16px;'
                    f'height:16px;border:1.5px dashed {color};border-radius:50%;'
                    f'margin-right:5px;vertical-align:middle;position:relative;">'
                    f'<span style="position:absolute;top:50%;left:50%;'
                    f'transform:translate(-50%,-50%);width:6px;height:6px;'
                    f'background:{color};border-radius:50%;"></span></span>')
        else:
            icon = (f'<span class="legend-dot" style="display:inline-block;width:12px;'
                    f'height:12px;background:{color};border:1px solid #999;'
                    f'border-radius:50%;margin-right:6px;vertical-align:middle;"></span>')
        html += (f'<span class="legend-item" data-layers="{layer_prefixes}" '
                 f'style="display:block;">{icon}{label}</span>')
    html += '</div>'
    return html


def _load_cb5_boundary():
    """Load CB5 boundary GeoJSON, downloading if needed."""
    if os.path.exists(CB5_BOUNDARY_PATH):
        with open(CB5_BOUNDARY_PATH) as f:
            return json.load(f)

    # Download from NYC geography GitHub repo
    print("    Downloading CB5 boundary GeoJSON...")
    import requests
    resp = requests.get(CB5_BOUNDARY_URL, timeout=30)
    resp.raise_for_status()
    all_districts = resp.json()

    # Extract Queens CB5 (GEOCODE=405)
    for feature in all_districts.get('features', []):
        if feature.get('properties', {}).get('GEOCODE') == 405:
            cb5_geojson = {"type": "FeatureCollection", "features": [feature]}
            with open(CB5_BOUNDARY_PATH, 'w') as f:
                json.dump(cb5_geojson, f)
            print(f"    Saved CB5 boundary to {CB5_BOUNDARY_PATH}")
            return cb5_geojson

    raise ValueError("Could not find GEOCODE=405 in community districts GeoJSON")


def _add_cb5_boundary(m):
    """Add real CB5 community district boundary to a folium map."""
    geojson = _load_cb5_boundary()
    folium.GeoJson(
        geojson,
        name='CB5 Boundary',
        style_function=lambda x: {
            'color': '#555555',
            'weight': 2,
            'opacity': 0.6,
            'fillColor': '#555555',
            'fillOpacity': 0.02,
            'dashArray': '6 3',
            'interactive': False,
        },
    ).add_to(m)


def _compute_before_after(data):
    """Compute before-after crash analysis for installed signal study locations.

    Only includes locations with confirmed installation dates
    (aw_installdate or signalinstalldate populated).

    Returns DataFrame with before/after crash counts and change metrics.
    """
    print("    Computing before-after analysis for installed locations...")

    cb5_studies_full = pd.read_csv(f'{OUTPUT_DIR}/data_cb5_signal_studies.csv', low_memory=False)
    cb5_studies_full['outcome'] = cb5_studies_full['statusdescription'].apply(_classify_outcome)
    approved = cb5_studies_full[
        (cb5_studies_full['outcome'] == 'approved') &
        (cb5_studies_full['requesttype'] != 'Accessible Pedestrian Signal')
    ]

    # Only truly installed: must have an install date
    installed = approved[
        approved['aw_installdate'].notna() | approved['signalinstalldate'].notna()
    ].copy()
    installed['install_date'] = pd.to_datetime(
        installed['aw_installdate'].fillna(installed['signalinstalldate']), errors='coerce')
    installed = installed.drop_duplicates(subset='referencenumber')

    # Merge coordinates from geocode cache
    cache = pd.read_csv(GEOCODE_CACHE_PATH, low_memory=False)
    installed = installed.merge(
        cache[['referencenumber', 'latitude', 'longitude']].drop_duplicates('referencenumber'),
        on='referencenumber', how='left', suffixes=('_orig', ''))
    installed = installed[installed['latitude'].notna() & installed['longitude'].notna()].copy()

    # Crash arrays for vectorized computation
    cb5_crashes = data['cb5_crashes']
    crash_lats = cb5_crashes['latitude'].values
    crash_lons = cb5_crashes['longitude'].values
    crash_dates = cb5_crashes['crash_date'].values
    crash_injured = cb5_crashes['number_of_persons_injured'].values
    crash_ped_inj = cb5_crashes['number_of_pedestrians_injured'].values

    DATA_START = pd.Timestamp(f'{STUDY_START_YEAR}-01-01')
    DATA_END = cb5_crashes['crash_date'].max()
    if pd.isna(DATA_END):
        DATA_END = pd.Timestamp(f'{LAST_COMPLETE_YEAR}-12-31')

    results = []
    for _, row in installed.iterrows():
        lat, lon = row['latitude'], row['longitude']
        install_dt = row['install_date']

        dists = _haversine_vectorized(lat, lon, crash_lats, crash_lons)
        within_150m = dists <= PROXIMITY_RADIUS_M

        # Equal time windows before and after, capped at 24 months
        months_before = (install_dt - DATA_START).days / 30.44
        months_after = (DATA_END - install_dt).days / 30.44
        window_months = min(months_before, months_after, 24)
        window_days = int(window_months * 30.44)

        before_start = install_dt - pd.Timedelta(days=window_days)
        after_end = install_dt + pd.Timedelta(days=window_days)

        before_mask = (within_150m &
                       (crash_dates >= np.datetime64(before_start)) &
                       (crash_dates < np.datetime64(install_dt)))
        after_mask = (within_150m &
                      (crash_dates >= np.datetime64(install_dt)) &
                      (crash_dates <= np.datetime64(after_end)))

        before_crashes = int(before_mask.sum())
        after_crashes = int(after_mask.sum())
        before_inj = int(crash_injured[before_mask].sum())
        after_inj = int(crash_injured[after_mask].sum())

        if before_crashes > 0:
            pct_change = ((after_crashes - before_crashes) / before_crashes) * 100
        elif after_crashes > 0:
            pct_change = 100.0
        else:
            pct_change = 0.0

        results.append({
            'referencenumber': row['referencenumber'],
            'requesttype': row['requesttype'],
            'mainstreet': format_nyc_street(row['mainstreet']),
            'crossstreet1': format_nyc_street(row['crossstreet1']),
            'daterequested': row.get('daterequested', None),
            'install_date': install_dt,
            'window_months': round(window_months, 1),
            'before_crashes': before_crashes,
            'after_crashes': after_crashes,
            'crash_change': after_crashes - before_crashes,
            'pct_change': round(pct_change, 1),
            'before_injuries': before_inj,
            'after_injuries': after_inj,
            'latitude': lat,
            'longitude': lon,
        })

    rdf = pd.DataFrame(results)
    decreased = (rdf['crash_change'] < 0).sum()
    increased = (rdf['crash_change'] > 0).sum()
    print(f"    Installed locations: {len(rdf)} "
          f"(crashes decreased: {decreased}, increased: {increased}, "
          f"no change: {len(rdf) - decreased - increased})")
    print(f"    Aggregate: {rdf['before_crashes'].sum()} before -> "
          f"{rdf['after_crashes'].sum()} after | "
          f"Injuries: {rdf['before_injuries'].sum()} -> {rdf['after_injuries'].sum()}")
    return rdf


def _export_map_json(signal_prox, srts_prox, cb5_crashes, data, before_after_df,
                     search_entries, top15, top10_crashes, cb5_aps=None):
    """Export all map layer data as a compact JSON file for the interactive map.

    Uses short property names to minimize file size.
    Output: output/map_data.json
    """
    print("    Exporting map data as JSON...")
    rng = np.random.RandomState(42)

    boundary_geojson = _load_cb5_boundary()

    # --- Crashes ---
    crash_with_coords = cb5_crashes[cb5_crashes['latitude'].notna()].copy()
    jitter_lat = rng.uniform(-0.00005, 0.00005, len(crash_with_coords))
    jitter_lon = rng.uniform(-0.00005, 0.00005, len(crash_with_coords))
    crashes_json = []
    for i, (_, r) in enumerate(crash_with_coords.iterrows()):
        inj = int(r.get('number_of_persons_injured', 0))
        killed = int(r.get('number_of_persons_killed', 0))
        ped_inj = int(r.get('number_of_pedestrians_injured', 0))
        ped_k = int(r.get('number_of_pedestrians_killed', 0))
        cyc_inj = int(r.get('number_of_cyclist_injured', 0))
        cyc_k = int(r.get('number_of_cyclist_killed', 0))
        mot_inj = int(r.get('number_of_motorist_injured', 0))
        mot_k = int(r.get('number_of_motorist_killed', 0))
        _on = format_nyc_street(r.get('on_street_name'))
        _off = format_nyc_street(r.get('off_street_name'))
        _factor = clean_whitespace(r.get('contributing_factor_vehicle_1'))
        _veh = clean_whitespace(r.get('vehicle_type_code1'))
        _date = ''
        try:
            _date = pd.to_datetime(r.get('crash_date')).strftime('%b %d, %Y')
        except Exception:
            pass
        _time = str(r.get('crash_time', '') or '').strip()

        rec = {
            'lat': round(r['latitude'], 6),
            'lon': round(r['longitude'], 6),
            'jlat': round(r['latitude'] + jitter_lat[i], 6),
            'jlon': round(r['longitude'] + jitter_lon[i], 6),
            'y': int(r.get('year', 0)),
            'inj': inj, 'k': killed,
            'pinj': ped_inj, 'pk': ped_k,
            'cinj': cyc_inj, 'ck': cyc_k,
            'minj': mot_inj, 'mk': mot_k,
            'on': _on, 'off': _off,
            'dt': _date, 'tm': _time,
            'fac': _factor, 'veh': _veh,
            'cid': str(r.get('collision_id', '')),
        }
        crashes_json.append(rec)

    # --- Signal studies ---
    def _signal_rec(row):
        ref = str(row.get('referencenumber', ''))
        main_st = format_nyc_street(row.get('mainstreet'))
        cross_st = format_nyc_street(row.get('crossstreet1'))
        req_type = clean_whitespace(row.get('requesttype'))
        status = clean_whitespace(row.get('statusdescription'))
        findings = clean_whitespace(row.get('findings'))
        school = format_school_name(row.get('schoolname'))
        vz = 1 if row.get('visionzero') == 'Yes' else 0
        req_date = ''
        try:
            req_date = pd.to_datetime(row.get('daterequested')).strftime('%b %d, %Y')
        except Exception:
            pass
        status_date = ''
        try:
            status_date = pd.to_datetime(row.get('statusdate')).strftime('%b %d, %Y')
        except Exception:
            pass
        return {
            'lat': round(row['latitude'], 6),
            'lon': round(row['longitude'], 6),
            'y': int(row.get('year', 0)),
            'ref': ref, 'main': main_st, 'cross': cross_st,
            'type': req_type, 'outcome': row['outcome'],
            'status': status, 'findings': findings,
            'school': school, 'vz': vz,
            'reqDt': req_date, 'statusDt': status_date,
            'cr': int(row.get('crashes_150m', 0)),
            'inj': int(row.get('injuries_150m', 0)),
            'pinj': int(row.get('ped_injuries_150m', 0)),
            'fat': int(row.get('fatalities_150m', 0)),
        }

    sig_with_coords = signal_prox[signal_prox['latitude'].notna()]
    denied_signals = [_signal_rec(r) for _, r in sig_with_coords[sig_with_coords['outcome'] == 'denied'].iterrows()]
    approved_signals = [_signal_rec(r) for _, r in sig_with_coords[sig_with_coords['outcome'] == 'approved'].iterrows()]

    # --- SRTS ---
    def _srts_rec(row):
        on_st = format_nyc_street(row.get('onstreet'))
        from_st = format_nyc_street(row.get('fromstreet'))
        to_st = format_nyc_street(row.get('tostreet'))
        proj_code = clean_whitespace(row.get('projectcode'))
        proj_status = clean_whitespace(row.get('projectstatus'))
        denial = clean_whitespace(row.get('denialreason'))
        direction = clean_whitespace(row.get('trafficdirectiondesc'))
        req_date = ''
        try:
            req_date = pd.to_datetime(row.get('requestdate')).strftime('%b %d, %Y')
        except Exception:
            pass
        closed_date = ''
        try:
            closed_date = pd.to_datetime(row.get('closeddate')).strftime('%b %d, %Y')
        except Exception:
            pass
        install_date = ''
        try:
            install_date = pd.to_datetime(row.get('installationdate')).strftime('%b %d, %Y')
        except Exception:
            pass
        return {
            'lat': round(row['latitude'], 6),
            'lon': round(row['longitude'], 6),
            'y': int(row.get('year', 0)),
            'on': on_st, 'from': from_st, 'to': to_st,
            'code': proj_code, 'outcome': row['outcome'],
            'projStatus': proj_status, 'denial': denial,
            'dir': direction,
            'reqDt': req_date, 'closedDt': closed_date,
            'installDt': install_date,
            'cr': int(row.get('crashes_150m', 0)),
            'inj': int(row.get('injuries_150m', 0)),
            'pinj': int(row.get('ped_injuries_150m', 0)),
            'fat': int(row.get('fatalities_150m', 0)),
        }

    srts_with_coords = srts_prox[srts_prox['latitude'].notna()]
    denied_srts = [_srts_rec(r) for _, r in srts_with_coords[srts_with_coords['outcome'] == 'denied'].iterrows()]
    approved_srts = [_srts_rec(r) for _, r in srts_with_coords[srts_with_coords['outcome'] == 'approved'].iterrows()]

    # --- APS ---
    aps_json = []
    if cb5_aps is not None and len(cb5_aps) > 0:
        for _, r in cb5_aps.iterrows():
            inst_date = ''
            try:
                inst_date = pd.to_datetime(r.get('date_insta')).strftime('%b %d, %Y')
            except Exception:
                pass
            aps_json.append({
                'lat': round(r['point_y'], 6),
                'lon': round(r['point_x'], 6),
                'y': int(r.get('year', 0)),
                'loc': format_aps_location(r.get('location')),
                'nta': clean_whitespace(r.get('ntaname')),
                'dt': inst_date,
            })

    # --- Effectiveness (before-after) ---
    eff_json = []
    if before_after_df is not None:
        for _, ba in before_after_df.iterrows():
            install_str = ''
            try:
                install_str = ba['install_date'].strftime('%b %d, %Y')
            except Exception:
                pass
            req_date = ''
            try:
                req_date = pd.to_datetime(ba.get('daterequested')).strftime('%b %d, %Y')
            except Exception:
                pass
            eff_json.append({
                'lat': round(ba['latitude'], 6),
                'lon': round(ba['longitude'], 6),
                'ref': str(ba.get('referencenumber', '')),
                'main': format_nyc_street(ba.get('mainstreet')),
                'cross': format_nyc_street(ba.get('crossstreet1')),
                'type': clean_whitespace(ba.get('requesttype')),
                'reqDt': req_date,
                'installDt': install_str,
                'wm': round(ba['window_months'], 1),
                'bc': int(ba['before_crashes']),
                'ac': int(ba['after_crashes']),
                'chg': int(ba['crash_change']),
                'pct': round(ba['pct_change'], 1),
                'bi': int(ba['before_injuries']),
                'ai': int(ba['after_injuries']),
            })

    # --- Top 15 ---
    top15_json = []
    for rank, (_, r) in enumerate(top15.iterrows(), 1):
        top15_json.append({
            'rank': rank,
            'lat': round(r['latitude'], 6),
            'lon': round(r['longitude'], 6),
            'name': r['location_name'],
            'dataset': r['dataset'],
            'type': r['request_info'],
            'cr': int(r['crashes_150m']),
            'inj': int(r['injuries_150m']),
            'pinj': int(r['ped_injuries_150m']),
            'fat': int(r['fatalities_150m']),
        })

    # --- Top 10 Crash Intersections ---
    top10_json = []
    for rank, (_, cr) in enumerate(top10_crashes.iterrows(), 1):
        top10_json.append({
            'rank': rank,
            'lat': round(cr['lat'], 6),
            'lon': round(cr['lon'], 6),
            'name': cr['intersection'],
            'cr': int(cr['crashes']),
            'inj': int(cr['injuries']),
            'pinj': int(cr['ped_injuries']),
            'cinj': int(cr['cyc_injuries']),
            'fat': int(cr['fatalities']),
        })

    # --- Search index ---
    search_json = {}
    for e in search_entries:
        ref = e.get('ref', '')
        if ref:
            search_json[ref] = {
                'lat': round(e['lat'], 6),
                'lon': round(e['lon'], 6),
                'label': e.get('label', ''),
                'type': e.get('type', ''),
                'outcome': e.get('outcome', ''),
            }

    map_data = {
        'crashes': crashes_json,
        'deniedSignals': denied_signals,
        'approvedSignals': approved_signals,
        'deniedSrts': denied_srts,
        'approvedSrts': approved_srts,
        'aps': aps_json,
        'effectiveness': eff_json,
        'top15': top15_json,
        'top10crashes': top10_json,
        'searchIndex': search_json,
        'boundary': boundary_geojson,
    }

    out_path = f'{OUTPUT_DIR}/map_data.json'
    with open(out_path, 'w') as f:
        json.dump(map_data, f, separators=(',', ':'))

    size_kb = os.path.getsize(out_path) / 1024
    print(f"    map_data.json ({size_kb:.0f} KB)")
    return map_data


def map_interactive_explorer(signal_prox, srts_prox, cb5_crashes, data,
                             before_after_df, search_entries, top15, top10_crashes, cb5_aps):
    """Generate the canonical lightweight interactive Leaflet explorer map.

    Vanilla Leaflet + MarkerCluster with verified SHA-384 SRI hashes, Option A
    light/dark theming, dynamic CARTO light_all/dark_all tiles, and external
    versioned map_data.json loading (no inline JSON duplication).
    Output: output/map_02_interactive_explorer.html
    """
    print("  Generating interactive explorer map...")

    json_path = f'{OUTPUT_DIR}/map_data.json'
    with open(json_path, 'rb') as f:
        data_version = hashlib.sha256(f.read()).hexdigest()[:12]

    html = _build_interactive_html(data_version)

    out_path = f'{OUTPUT_DIR}/map_02_interactive_explorer.html'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    _strip_trailing_whitespace(out_path)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"    Interactive explorer map saved ({size_kb:.0f} KB, data v={data_version})")


def _build_interactive_html(data_version):
    """Build HTML for the interactive explorer map (EA Civic Map Shell v2).

    Loads templates/map_02_template.html and injects versioned map_data.json hash
    and study year bounds (defaults to 2020-2025).
    """
    _start_year_options = ''.join(
        f'<option value="{y}"{" selected" if y == STUDY_START_YEAR else ""}>{y}</option>'
        for y in range(STUDY_START_YEAR, LAST_COMPLETE_YEAR + 1)
    )
    _end_year_options = ''.join(
        f'<option value="{y}"{" selected" if y == LAST_COMPLETE_YEAR else ""}>{y}</option>'
        for y in range(STUDY_START_YEAR, LAST_COMPLETE_YEAR + 1)
    )
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'map_02_template.html')
    with open(tpl_path, encoding='utf-8') as f:
        tpl = f.read()
    return (
        tpl.replace('__DATA_VERSION__', data_version)
           .replace('__START_YEAR_OPTIONS__', _start_year_options)
           .replace('__END_YEAR_OPTIONS__', _end_year_options)
           .replace('__STUDY_START_YEAR__', str(STUDY_START_YEAR))
           .replace('__LAST_COMPLETE_YEAR__', str(LAST_COMPLETE_YEAR))
    )


def prepare_map_layers(signal_prox, srts_prox, cb5_crashes, data=None):
    """Prepare map layer exports, search index, spotlights, and map_data.json.

    Replaces the retired legacy 17 MB Folium overlay map with pure data export
    feeding the canonical interactive Leaflet explorer (map_02_interactive_explorer.html).
    """
    print("  Preparing map layers and map_data.json...")
    search_entries = []

    if data is not None and 'cb5_no_aps' in data:
        _date_source = data['cb5_no_aps'][['referencenumber', 'daterequested', 'statusdate']].drop_duplicates('referencenumber')
        for col in ['daterequested', 'statusdate']:
            if col not in signal_prox.columns or signal_prox[col].isna().all():
                signal_prox = signal_prox.drop(columns=[col], errors='ignore')
                signal_prox = signal_prox.merge(
                    _date_source[['referencenumber', col]], on='referencenumber', how='left')

    _sig_denied = signal_prox[signal_prox['outcome'] == 'denied']
    _sig_approved = signal_prox[signal_prox['outcome'] == 'approved']
    _srts_denied = srts_prox[srts_prox['outcome'] == 'denied']
    _srts_approved = srts_prox[srts_prox['outcome'] == 'approved']
    n_sig_denied = int(_sig_denied['latitude'].notna().sum())
    n_sig_approved = int(_sig_approved['latitude'].notna().sum())
    n_srts_denied = int(_srts_denied['latitude'].notna().sum())
    n_srts_approved = int(_srts_approved['latitude'].notna().sum())

    crash_with_coords = cb5_crashes[cb5_crashes['latitude'].notna()].copy()

    for outcome_label, subset in [('denied', _sig_denied), ('approved', _sig_approved)]:
        for _, row in subset.iterrows():
            if pd.isna(row['latitude']):
                continue
            search_entries.append({
                'ref': row.get('referencenumber', ''),
                'lat': row['latitude'],
                'lon': row['longitude'],
                'label': format_nyc_intersection(row.get('mainstreet'), row.get('crossstreet1'), sort_pair=False),
                'type': clean_whitespace(row.get('requesttype')),
                'outcome': outcome_label,
            })

    for outcome_label, subset in [('denied', _srts_denied), ('approved', _srts_approved)]:
        for _, row in subset.iterrows():
            if pd.isna(row['latitude']):
                continue
            search_entries.append({
                'ref': clean_whitespace(row.get('projectcode')),
                'lat': row['latitude'],
                'lon': row['longitude'],
                'label': f"{format_nyc_street(row.get('onstreet'))} ({format_nyc_street(row.get('fromstreet'))} to {format_nyc_street(row.get('tostreet'))})",
                'type': 'Speed Bump',
                'outcome': outcome_label,
            })

    _aps_path = f'{DATA_DIR}/aps_installed_citywide.csv'
    cb5_aps = None
    n_aps = 0
    if os.path.exists(_aps_path):
        aps_installed = pd.read_csv(_aps_path)
        aps_installed['point_x'] = pd.to_numeric(aps_installed['point_x'], errors='coerce')
        aps_installed['point_y'] = pd.to_numeric(aps_installed['point_y'], errors='coerce')
        aps_installed['date_insta'] = pd.to_datetime(aps_installed['date_insta'], errors='coerce')
        aps_installed['year'] = aps_installed['date_insta'].dt.year

        cb5_aps = aps_installed[aps_installed['borocd'].astype(str).str.strip() == '405'].copy()
        cb5_aps = cb5_aps[cb5_aps['year'].between(STUDY_START_YEAR, LAST_COMPLETE_YEAR)]
        cb5_aps = cb5_aps[cb5_aps['point_x'].notna() & cb5_aps['point_y'].notna()]
        _aps_poly = prep(_load_cb5_polygon())
        inside = cb5_aps.apply(lambda r: _aps_poly.contains(Point(r['point_x'], r['point_y'])), axis=1)
        cb5_aps = cb5_aps[inside]
        n_aps = len(cb5_aps)
        for _, row in cb5_aps.iterrows():
            location = format_aps_location(row.get('location'))
            search_entries.append({
                'ref': '',
                'lat': row['point_y'],
                'lon': row['point_x'],
                'label': location,
                'type': 'APS',
                'outcome': 'installed',
            })
        print(f"    APS Installed layer: {n_aps} locations")
    else:
        print("    WARNING: APS installed data not found — run scripts_fetch_data.py")

    before_after_df = _compute_before_after(data) if data is not None else None

    sig_denied = signal_prox[
        (signal_prox['outcome'] == 'denied') & signal_prox['latitude'].notna()
    ].copy()
    sig_denied['location_name'] = sig_denied.apply(
        lambda r: _normalize_intersection(r['mainstreet'], r['crossstreet1']), axis=1)
    sig_denied['dataset'] = 'Signal Study'
    sig_denied['request_info'] = sig_denied['requesttype']
    common_cols = ['location_name', 'dataset', 'request_info', 'latitude', 'longitude',
                   'crashes_150m', 'injuries_150m', 'ped_injuries_150m', 'fatalities_150m']
    spotlight_data = sig_denied[common_cols].copy()
    spotlight_data = spotlight_data.sort_values('crashes_150m', ascending=False).drop_duplicates(
        subset=['location_name'], keep='first')
    spotlight_data = _spatial_dedup(spotlight_data, radius_m=150)
    top15 = spotlight_data.nlargest(15, 'crashes_150m')

    crash_with_streets = crash_with_coords.dropna(subset=['on_street_name', 'off_street_name']).copy()
    crash_with_streets['intersection'] = crash_with_streets.apply(
        lambda r: _normalize_intersection(r['on_street_name'], r['off_street_name']), axis=1)
    crash_agg = crash_with_streets.groupby('intersection').agg(
        crashes=('collision_id', 'count'),
        injuries=('number_of_persons_injured', 'sum'),
        ped_injuries=('number_of_pedestrians_injured', 'sum'),
        cyc_injuries=('number_of_cyclist_injured', 'sum'),
        fatalities=('number_of_persons_killed', 'sum'),
        lat=('latitude', 'median'),
        lon=('longitude', 'median'),
    ).reset_index().sort_values('crashes', ascending=False)
    top10_crashes = crash_agg.head(10)

    print("    Exporting map layer spreadsheets...")
    crash_cols = ['crash_date', 'crash_time', 'on_street_name', 'off_street_name',
                  'number_of_persons_injured', 'number_of_persons_killed',
                  'number_of_pedestrians_injured', 'number_of_pedestrians_killed',
                  'number_of_cyclist_injured', 'number_of_cyclist_killed',
                  'number_of_motorist_injured', 'number_of_motorist_killed',
                  'contributing_factor_vehicle_1', 'vehicle_type_code1',
                  'collision_id', 'latitude', 'longitude']
    _crash_export = crash_with_coords[[c for c in crash_cols if c in crash_with_coords.columns]].copy()
    if 'on_street_name' in _crash_export.columns:
        _crash_export['on_street_name'] = _crash_export['on_street_name'].apply(format_nyc_street)
    if 'off_street_name' in _crash_export.columns:
        _crash_export['off_street_name'] = _crash_export['off_street_name'].apply(format_nyc_street)
    _crash_export['Source Dataset'] = 'Motor Vehicle Collisions [h9gi-nx95]'
    _crash_export.to_csv(f'{OUTPUT_DIR}/map_layer_crashes.csv', index=False)

    _sig_full = data['cb5_no_aps'] if data is not None else pd.DataFrame()
    _sig_enrich_cols = ['referencenumber', 'daterequested', 'statusdate', 'findings',
                        'schoolname', 'visionzero']
    _sig_enrich = _sig_full[[c for c in _sig_enrich_cols if c in _sig_full.columns]].drop_duplicates('referencenumber')
    sig_cols = ['referencenumber', 'mainstreet', 'crossstreet1', 'requesttype',
                'outcome', 'daterequested', 'statusdate', 'statusdescription',
                'findings', 'schoolname', 'visionzero',
                'crashes_150m', 'injuries_150m', 'ped_injuries_150m', 'fatalities_150m',
                'latitude', 'longitude']
    for outcome_label, subset in [('denied', _sig_denied), ('approved', _sig_approved)]:
        _exp = subset[subset['latitude'].notna()].copy()
        if len(_sig_enrich) > 0:
            _exp = _exp.merge(_sig_enrich, on='referencenumber', how='left', suffixes=('', '_orig'))
        _exp = _exp[[c for c in sig_cols if c in _exp.columns]].copy()
        if 'mainstreet' in _exp.columns:
            _exp['mainstreet'] = _exp['mainstreet'].apply(format_nyc_street)
        if 'crossstreet1' in _exp.columns:
            _exp['crossstreet1'] = _exp['crossstreet1'].apply(format_nyc_street)
        if 'schoolname' in _exp.columns:
            _exp['schoolname'] = _exp['schoolname'].apply(format_school_name)
        if 'statusdescription' in _exp.columns:
            _exp['statusdescription'] = _exp['statusdescription'].apply(clean_whitespace)
        _exp['Source File'] = 'data_cb5_signal_studies.csv'
        _exp.to_csv(f'{OUTPUT_DIR}/map_layer_{outcome_label}_signals.csv', index=False)

    srts_cols = ['projectcode', 'onstreet', 'fromstreet', 'tostreet',
                 'outcome', 'requestdate', 'closeddate', 'projectstatus', 'denialreason',
                 'installationdate', 'trafficdirectiondesc',
                 'crashes_150m', 'injuries_150m', 'ped_injuries_150m', 'fatalities_150m',
                 'latitude', 'longitude']
    for outcome_label, subset in [('denied', _srts_denied), ('approved', _srts_approved)]:
        _exp = subset[[c for c in srts_cols if c in subset.columns]].copy()
        _exp = _exp[_exp['latitude'].notna()].copy()
        for _sc in ('onstreet', 'fromstreet', 'tostreet'):
            if _sc in _exp.columns:
                _exp[_sc] = _exp[_sc].apply(format_nyc_street)
        _exp['Source File'] = 'srts_citywide.csv'
        _exp.to_csv(f'{OUTPUT_DIR}/map_layer_{outcome_label}_speed_bumps.csv', index=False)

    if n_aps > 0:
        aps_cols = ['location', 'date_insta', 'ntaname', 'point_x', 'point_y']
        _aps_export = cb5_aps[[c for c in aps_cols if c in cb5_aps.columns]].copy()
        if 'location' in _aps_export.columns:
            _aps_export['location'] = _aps_export['location'].apply(format_aps_location)
        _aps_export = _aps_export.rename(columns={'point_y': 'latitude', 'point_x': 'longitude'})
        _aps_export['Source Dataset'] = 'APS Installed Locations [de3m-c5p4]'
        _aps_export.to_csv(f'{OUTPUT_DIR}/map_layer_aps_installed.csv', index=False)

    _top15_export = top15.copy()
    _top15_export['Source File'] = 'data_cb5_signal_studies.csv'
    _top15_export.to_csv(f'{OUTPUT_DIR}/map_layer_top15_denied.csv', index=False)

    print(f"      map_layer_crashes.csv ({len(_crash_export):,} rows)")
    print(f"      map_layer_denied_signals.csv ({n_sig_denied:,} rows)")
    print(f"      map_layer_approved_signals.csv ({n_sig_approved:,} rows)")
    print(f"      map_layer_denied_speed_bumps.csv ({n_srts_denied:,} rows)")
    print(f"      map_layer_approved_speed_bumps.csv ({n_srts_approved:,} rows)")
    if n_aps > 0:
        print(f"      map_layer_aps_installed.csv ({n_aps:,} rows)")
    print(f"      map_layer_top15_denied.csv (15 rows)")

    _export_map_json(signal_prox, srts_prox, cb5_crashes, data, before_after_df,
                     search_entries, top15, top10_crashes,
                     cb5_aps=cb5_aps if n_aps > 0 else None)

    return before_after_df, search_entries, top15, top10_crashes, (cb5_aps if n_aps > 0 else None)


# ============================================================
# Step 4: Static Charts (Matplotlib)
# ============================================================

def _draw_proximity_panel(df, title_prefix, filename, chart_label):
    """Draw a single-panel crash proximity chart for denied and approved records."""
    metrics = ['crashes_150m', 'injuries_150m', 'ped_injuries_150m']
    metric_labels = ['Crashes', 'Injuries', 'Ped. Injuries']

    geocoded = df[df['latitude'].notna()]
    denied = geocoded[geocoded['outcome'] == 'denied']
    approved = geocoded[geocoded['outcome'] == 'approved']

    fig, ax = plt.subplots(figsize=(10, 6))

    x = np.arange(len(metrics))
    width = 0.35

    denied_medians = [denied[m].median() for m in metrics]
    approved_medians = [approved[m].median() for m in metrics]

    bars1 = ax.bar(x - width/2, denied_medians, width,
                   label=f'Denied (n={len(denied)})',
                   color=COLORS['denied'], edgecolor='black', zorder=3)
    bars2 = ax.bar(x + width/2, approved_medians, width,
                   label=f'Approved (n={len(approved)})',
                   color=COLORS['approved'], edgecolor='black', zorder=3)

    for bars in [bars1, bars2]:
        for bar in bars:
            val = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, val + 0.2,
                    f'{val:.1f}', ha='center', va='bottom',
                    fontsize=9, fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(metric_labels, fontsize=10)
    ax.set_ylabel('Median Count within 150m', fontweight='bold')
    ax.set_title(f'Crash Proximity: Denied and Approved {title_prefix}\n(n={len(denied)+len(approved):,}, Median Crash Metrics, {STUDY_START_YEAR}–{LAST_COMPLETE_YEAR})',
                 fontweight='bold', fontsize=12)
    ax.legend(loc='upper right')
    ax.xaxis.grid(False)

    denied_crashes = denied['crashes_150m'].dropna()
    approved_crashes = approved['crashes_150m'].dropna()
    if len(denied_crashes) > 0 and len(approved_crashes) > 0:
        U, p = _mann_whitney_u(denied_crashes, approved_crashes)
        sig_text = f'p={p:.4f}' if p >= 0.0001 else 'p<0.0001'
        if p < 0.05:
            sig_text += ' *'
        ax.annotate(
            f'Mann-Whitney U ({sig_text})',
            xy=(0.98, 0.82), xycoords='axes fraction',
            ha='right', fontsize=9, style='italic',
            bbox=dict(boxstyle='round', facecolor='lightyellow', edgecolor='gray', alpha=0.9)
        )

    fig.text(0.01, -0.02,
             'Source: NYC Open Data — 150m radius (~1.5 blocks, Vision Zero standard)\n'
             f'Crash data: injury and fatal crashes [{STUDY_START_YEAR}–{LAST_COMPLETE_YEAR}], Motor Vehicle Collisions [h9gi-nx95]',
             ha='left', fontsize=9, style='italic', color='#333333')

    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/{filename}', dpi=300,
                bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close()
    print(f"    Chart {chart_label} saved.")


def chart_09_crash_proximity(signal_prox, srts_prox):
    """Chart 09 + 09a: Crash Proximity — split into individual panels."""
    print("  Generating Chart 09: Signal Study Crash Proximity...")
    _draw_proximity_panel(signal_prox, 'Signal Study Locations',
                          'chart_09_crash_proximity_analysis.png', '09')

    print("  Generating Chart 09a: Speed Bump Crash Proximity...")
    _draw_proximity_panel(srts_prox, 'Speed Bump Locations',
                          'chart_09a_srts_crash_proximity.png', '09a')


def _normalize_intersection(street_a, street_b):
    """Normalize intersection name via canonical NYC DCP LION-aligned formatting and sorting.

    Ensures 'METROPOLITAN AVENUE & COOPER AVENUE' == 'Cooper Ave & Metropolitan Ave'.
    """
    return format_nyc_intersection(street_a, street_b, sort_pair=True)


def _spatial_dedup(df, radius_m=100):
    """Spatially de-duplicate locations: if two entries are within radius_m,
    keep only the one with the highest crash count.

    Uses greedy approach: sort descending, skip any row within radius of
    an already-selected row.
    """
    if len(df) == 0:
        return df
    sorted_df = df.sort_values('crashes_150m', ascending=False).reset_index(drop=True)
    selected_idx = []
    selected_coords = []

    for i, row in sorted_df.iterrows():
        lat, lon = row['latitude'], row['longitude']
        too_close = False
        for slat, slon in selected_coords:
            # Approximate distance in meters
            dlat = (lat - slat) * 111_320
            dlon = (lon - slon) * 111_320 * math.cos(math.radians(lat))
            dist = math.sqrt(dlat**2 + dlon**2)
            if dist < radius_m:
                too_close = True
                break
        if not too_close:
            selected_idx.append(i)
            selected_coords.append((lat, lon))

    return sorted_df.loc[selected_idx].reset_index(drop=True)


def _prepare_top15_denied(signal_prox):
    """Shared: prepare de-duplicated denied signal study locations."""
    sig_denied = signal_prox[
        (signal_prox['outcome'] == 'denied') & signal_prox['latitude'].notna()
    ].copy()
    sig_denied['location_name'] = sig_denied.apply(
        lambda r: _normalize_intersection(r['mainstreet'], r['crossstreet1']), axis=1)

    common_cols = ['location_name', 'latitude', 'longitude',
                   'crashes_150m', 'injuries_150m', 'ped_injuries_150m', 'fatalities_150m']
    denied = sig_denied[common_cols].copy()

    deduped = denied.sort_values('crashes_150m', ascending=False).drop_duplicates(
        subset=['location_name'], keep='first')
    deduped = _spatial_dedup(deduped, radius_m=150)
    return deduped


def _abbrev_street(name):
    """Abbreviate street names for chart readability."""
    return (name
            .replace(' Avenue', ' Ave')
            .replace(' Street', ' St')
            .replace(' Road', ' Rd')
            .replace(' Boulevard', ' Blvd')
            .replace(' Turnpike', ' Tpke')
            .replace(' Place', ' Pl')
            .replace(' Lane', ' Ln')
            .replace(' Drive', ' Dr'))


def chart_09b_top_denied_by_crashes(signal_prox):
    """Chart 09b: Top 15 Denied Signal Study Intersections by Crash Count."""
    print("  Generating Chart 09b: Top 15 Denied by Crash Count...")

    deduped = _prepare_top15_denied(signal_prox)
    n_unique = len(deduped)

    top15 = deduped.nlargest(15, 'crashes_150m').reset_index(drop=True)
    top15['label'] = top15['location_name'].apply(lambda n: _abbrev_street(n[:45]))

    fig, ax = plt.subplots(figsize=(10, 6))

    top15_rev = top15.iloc[::-1].reset_index(drop=True)
    y = np.arange(len(top15_rev))

    bars = ax.barh(y, top15_rev['crashes_150m'], color=COLORS['denied'],
                   edgecolor='black', zorder=3)
    for i, val in enumerate(top15_rev['crashes_150m'].astype(int)):
        ax.text(val + 0.5, i, str(val),
                va='center', ha='left', fontsize=9, fontweight='bold')

    ax.set_yticks(y)
    ax.set_yticklabels(top15_rev['label'], fontsize=9)
    ax.set_xlabel('Crashes within 150m', fontweight='bold')
    ax.set_title(f'Top 15 Denied Signal Study Intersections by Nearby Crash Count\n(150m Radius, n={n_unique:,} unique denied intersections, {STUDY_START_YEAR}–{LAST_COMPLETE_YEAR})',
                 fontweight='bold', fontsize=12)
    ax.yaxis.grid(False)

    fig.text(0.01, -0.02,
             'Source: NYC Open Data — Signal Studies [w76s-c5u4], Motor Vehicle Collisions [h9gi-nx95]',
             ha='left', fontsize=9, style='italic', color='#333333')

    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/chart_09b_denied_locations_crash_ranking.png', dpi=300,
                bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close()
    print("    Chart 09b saved.")


def chart_09c_top_denied_by_injuries(signal_prox):
    """Chart 09c: Top 15 Denied Signal Study Intersections by Injury Count."""
    print("  Generating Chart 09c: Top 15 Denied by Injury Count...")

    deduped = _prepare_top15_denied(signal_prox)
    n_unique = len(deduped)

    top15_inj = deduped.nlargest(15, 'injuries_150m').reset_index(drop=True)
    top15_inj['other_injuries'] = (top15_inj['injuries_150m'] - top15_inj['ped_injuries_150m']).clip(lower=0)
    top15_inj['label'] = top15_inj['location_name'].apply(lambda n: _abbrev_street(n[:45]))

    fig, ax = plt.subplots(figsize=(10, 6))

    top15_inj_rev = top15_inj.iloc[::-1].reset_index(drop=True)
    y = np.arange(len(top15_inj_rev))

    ped_vals = top15_inj_rev['ped_injuries_150m'].astype(int).values
    other_vals = top15_inj_rev['other_injuries'].astype(int).values

    ax.barh(y, ped_vals, color=COLORS['denied'],
            edgecolor='black', linewidth=0.5, zorder=3, label='Pedestrian Injuries')
    ax.barh(y, other_vals, left=ped_vals, color=COLORS['crash_alt'],
            edgecolor='black', linewidth=0.5, zorder=3, label='Other Injuries')

    for i, (p, o) in enumerate(zip(ped_vals, other_vals)):
        total = p + o
        ax.text(total + 0.5, i, str(total),
                va='center', ha='left', fontsize=9, fontweight='bold')

    ax.set_yticks(y)
    ax.set_yticklabels(top15_inj_rev['label'], fontsize=9)
    ax.set_xlabel('Persons Injured within 150m', fontweight='bold')
    ax.set_title(f'Top 15 Denied Signal Study Intersections by Nearby Injuries\n(150m Radius, n={n_unique:,} unique denied intersections, {STUDY_START_YEAR}–{LAST_COMPLETE_YEAR})',
                 fontweight='bold', fontsize=12)
    ax.yaxis.grid(False)
    ax.legend(loc='lower right', fontsize=8, framealpha=0.9)

    fig.text(0.01, -0.02,
             'Source: NYC Open Data — Signal Studies [w76s-c5u4], Motor Vehicle Collisions [h9gi-nx95]',
             ha='left', fontsize=9, style='italic', color='#333333')

    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/chart_09c_denied_locations_injury_ranking.png', dpi=300,
                bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close()
    print("    Chart 09c saved.")


def chart_15_srts_funnel():
    """Chart 15: SRTS Approval Funnel — what happens after DOT approves a speed bump."""
    print("  Generating Chart 15: SRTS Approval Funnel...")

    # Full CB5 pipeline: cb=405 + polygon filter
    cb5 = _load_cb5_srts_full()
    cb5['requestdate'] = pd.to_datetime(cb5['requestdate'], errors='coerce')
    feasible = cb5[cb5['segmentstatusdescription'] == 'Feasible'].copy()

    min_yr = int(feasible['requestdate'].dt.year.min())
    max_yr = min(int(feasible['requestdate'].dt.year.max()), LAST_COMPLETE_YEAR)

    feasible['install_dt'] = pd.to_datetime(feasible['installationdate'], errors='coerce')

    # Categorize outcomes (mutually exclusive, must sum to total)
    installed = feasible[
        feasible['install_dt'].notna() &
        ~feasible['projectstatus'].str.contains('Cancel|Reject|denied', case=False, na=False)
    ]
    cancelled = feasible[
        feasible['projectstatus'].str.contains('Cancel|Reject|denied', case=False, na=False)
    ]
    still_open = feasible[
        feasible['install_dt'].isna() &
        ~feasible['projectstatus'].str.contains('Cancel|Reject|denied|Closed', case=False, na=False)
    ]
    # "Closed" without install date and without Cancel/Reject — administrative closures
    closed_other = feasible[
        feasible['install_dt'].isna() &
        feasible['projectstatus'].str.contains('Closed', case=False, na=False) &
        ~feasible['projectstatus'].str.contains('Cancel|Reject|denied', case=False, na=False)
    ]

    n_total = len(feasible)
    n_installed = len(installed)
    n_cancelled = len(cancelled)
    n_waiting = len(still_open)
    n_closed = len(closed_other)

    # --- Two-panel layout ---
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), gridspec_kw={'width_ratios': [1, 2]})

    # Left panel: total approved as a single reference bar
    axes[0].bar(['Approved\nby DOT'], [n_total], color=COLORS['primary'],
                edgecolor='#132230', linewidth=0.7, zorder=3, width=0.5)
    axes[0].text(0, n_total + 5, str(n_total), ha='center', va='bottom',
                 fontweight='bold', fontsize=14)
    axes[0].set_ylabel('Number of Requests', fontweight='bold')
    axes[0].set_title(f'Total Approved\n({min_yr}–{max_yr})', fontweight='bold', fontsize=12)
    axes[0].set_ylim(0, n_total * 1.15)
    axes[0].xaxis.grid(False)

    # Right panel: what happened to them (only include Closed if any exist)
    categories = ['Confirmed\nInstalled', 'Cancelled /\nRejected']
    values = [n_installed, n_cancelled]
    bar_colors = [COLORS['approved'], COLORS['citywide']]
    if n_closed > 0:
        categories.append('Closed\n(No Install)')
        values.append(n_closed)
        bar_colors.append('#94A3B8')
    categories.append('Still\nWaiting')
    values.append(n_waiting)
    bar_colors.append('#64748B')

    bars = axes[1].bar(categories, values, color=bar_colors, edgecolor='#132230', linewidth=0.7, zorder=3, width=0.58)

    for bar, val in zip(bars, values):
        pct = val / n_total * 100
        pct_str = f'{pct:.1f}%' if pct < 1 else f'{pct:.0f}%'
        axes[1].text(bar.get_x() + bar.get_width()/2, val + 3,
                     f'{val}\n({pct_str})', ha='center', va='bottom',
                     fontweight='bold', fontsize=11)

    axes[1].set_ylabel('Number of Requests', fontweight='bold')
    axes[1].set_title(f'Outcome of {n_total} Approved Requests', fontweight='bold', fontsize=12)
    axes[1].set_ylim(0, max(values) * 1.25)
    axes[1].xaxis.grid(False)

    # Median wait annotation — positioned cleanly in upper-right empty space above Still Waiting
    still_open_dt = pd.to_datetime(still_open['requestdate'], errors='coerce')
    if len(still_open_dt.dropna()) > 0:
        median_years = (pd.Timestamp.now() - still_open_dt).dt.days.median() / 365.25
        axes[1].annotate(f'Still waiting median age: {median_years:.1f} years',
                         xy=(0.98, 0.92), xycoords='axes fraction',
                         ha='right', va='top', fontsize=9,
                         style='italic', color='#132230',
                         bbox=dict(boxstyle='round,pad=0.35', facecolor='#F8F7F4',
                                   edgecolor='#DCE2E8', alpha=0.95))

    fig.suptitle(f'QCB5 DOT-Approved Speed Bumps: Post-Approval Outcomes\n(n={n_total:,}, {min_yr}–{max_yr})',
                 fontweight='bold', fontsize=14, y=1.02)
    fig.text(0.01, -0.03,
             'Source: NYC Open Data — Speed Reducer Tracking System [9n6h-pt9g] | "Feasible" = DOT engineering approval\n'
             'Cancelled/Rejected and Closed per DOT projectstatus field',
             ha='left', fontsize=9, style='italic', color='#333333')

    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/chart_15_srts_funnel.png', dpi=300,
                bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close()

    # Save accompanying CSV
    rows_15 = [
        {'Category': 'Total Approved (Feasible)', 'Count': n_total, 'Percent': 100.0},
        {'Category': 'Confirmed Installed', 'Count': n_installed, 'Percent': round(n_installed / n_total * 100, 1)},
        {'Category': 'Cancelled / Rejected', 'Count': n_cancelled, 'Percent': round(n_cancelled / n_total * 100, 1)},
    ]
    if n_closed > 0:
        rows_15.append({'Category': 'Closed (No Install)', 'Count': n_closed, 'Percent': round(n_closed / n_total * 100, 1)})
    rows_15.append({'Category': 'Still Waiting', 'Count': n_waiting, 'Percent': round(n_waiting / n_total * 100, 1)})
    table_15 = pd.DataFrame(rows_15)
    table_15['Source File'] = 'srts_citywide.csv'
    table_15.to_csv(f'{OUTPUT_DIR}/table_15_srts_funnel.csv', index=False)
    print("    Chart 15 saved.")


# ============================================================
# Step 5: Data Tables
# ============================================================

def save_data_tables(signal_prox, srts_prox):
    """Save CSV data tables for all Part 2 outputs."""
    print("  Saving data tables...")

    # Table 09: Per-location crash proximity (with reference numbers for traceability)
    sig_rows = signal_prox[signal_prox['latitude'].notna()].copy()
    sig_rows['location_name'] = (
        sig_rows['mainstreet'].fillna('') + ' & ' + sig_rows['crossstreet1'].fillna('')
    ).str.title()
    sig_rows['dataset'] = 'Signal Study'
    sig_rows['reference_id'] = sig_rows['referencenumber']
    sig_rows['request_year'] = sig_rows['year']
    sig_rows['request_type'] = sig_rows['requesttype']
    sig_rows['source_file'] = 'data_cb5_signal_studies.csv'

    srts_rows = srts_prox[srts_prox['latitude'].notna()].copy()
    srts_rows['location_name'] = srts_rows['onstreet'].fillna('').str.title()
    srts_rows['dataset'] = 'SRTS'
    srts_rows['reference_id'] = srts_rows['projectcode']
    srts_rows['request_year'] = srts_rows['year']
    srts_rows['request_type'] = 'Speed Bump'
    srts_rows['source_file'] = 'srts_citywide.csv'

    common_cols = ['reference_id', 'location_name', 'dataset', 'request_type', 'outcome',
                   'request_year', 'source_file', 'latitude', 'longitude',
                   'crashes_150m', 'injuries_150m', 'ped_injuries_150m', 'fatalities_150m']
    table_09 = pd.concat([
        sig_rows[[c for c in common_cols if c in sig_rows.columns]],
        srts_rows[[c for c in common_cols if c in srts_rows.columns]]
    ], ignore_index=True)
    table_09 = table_09.sort_values('crashes_150m', ascending=False)
    table_09 = table_09.rename(columns={'source_file': 'Source File'})
    table_09.to_csv(f'{OUTPUT_DIR}/table_09_crash_proximity_by_location.csv', index=False)

    # Table 09b: Aggregate comparison — denied and approved
    rows = []
    for dataset_label, df in [('Signal Studies', signal_prox), ('SRTS', srts_prox)]:
        for outcome in ['denied', 'approved']:
            subset = df[(df['outcome'] == outcome) & df['crashes_150m'].notna()]
            if len(subset) == 0:
                continue
            rows.append({
                'Dataset': dataset_label,
                'Outcome': outcome,
                'N': len(subset),
                'Mean Crashes 150m': round(subset['crashes_150m'].mean(), 1),
                'Median Crashes 150m': round(subset['crashes_150m'].median(), 1),
                'Mean Injuries 150m': round(subset['injuries_150m'].mean(), 1),
                'Median Injuries 150m': round(subset['injuries_150m'].median(), 1),
                'Mean Ped Injuries 150m': round(subset['ped_injuries_150m'].mean(), 1),
                'Median Ped Injuries 150m': round(subset['ped_injuries_150m'].median(), 1),
            })

    table_09b = pd.DataFrame(rows)

    # Add p-values
    for dataset_label, df in [('Signal Studies', signal_prox), ('SRTS', srts_prox)]:
        denied = df[(df['outcome'] == 'denied') & df['crashes_150m'].notna()]['crashes_150m']
        approved = df[(df['outcome'] == 'approved') & df['crashes_150m'].notna()]['crashes_150m']
        if len(denied) > 0 and len(approved) > 0:
            _, p = _mann_whitney_u(denied, approved)
            mask = table_09b['Dataset'] == dataset_label
            table_09b.loc[mask, 'Mann-Whitney p-value (crashes)'] = round(p, 6)

    table_09b['Source Dataset'] = table_09b['Dataset'].apply(
        lambda d: 'data_cb5_signal_studies.csv' if d == 'Signal Studies'
        else 'srts_citywide.csv')
    table_09b.to_csv(f'{OUTPUT_DIR}/table_09b_aggregate_comparison.csv', index=False)

    # Table 09c: Top denied signal study intersections by crashes (ranked list for article)
    # Signal studies only — intersection-level precision. SRTS excluded due to
    # segment-based coordinates creating methodological issues with 150m overlap.
    sig_denied = signal_prox[
        (signal_prox['outcome'] == 'denied') & signal_prox['latitude'].notna()
    ].copy()
    sig_denied['location_name'] = sig_denied.apply(
        lambda r: _normalize_intersection(r['mainstreet'], r['crossstreet1']), axis=1)
    sig_denied['dataset'] = 'Signal Study'
    sig_denied['request_type'] = sig_denied.get('requesttype', 'N/A')
    sig_denied['reference_id'] = sig_denied['referencenumber']
    sig_denied['request_year'] = sig_denied['year']
    sig_denied['source_file'] = 'data_cb5_signal_studies.csv'

    common_cols_c = ['reference_id', 'location_name', 'dataset', 'request_type',
                     'request_year', 'source_file', 'latitude', 'longitude',
                     'crashes_150m', 'injuries_150m', 'ped_injuries_150m', 'fatalities_150m']
    combined = sig_denied[[c for c in common_cols_c if c in sig_denied.columns]].copy()
    # De-duplicate: name-based then spatial
    combined = combined.sort_values('crashes_150m', ascending=False).drop_duplicates(
        subset=['location_name'], keep='first')
    combined = _spatial_dedup(combined, radius_m=150)
    table_09c = combined.nlargest(25, 'crashes_150m').reset_index(drop=True)
    table_09c.index = table_09c.index + 1
    table_09c.index.name = 'Rank'
    table_09c = table_09c.rename(columns={'source_file': 'Source File'})
    table_09c.to_csv(f'{OUTPUT_DIR}/table_09c_top_denied_by_crashes.csv')

    print(f"    table_09: {len(table_09)} locations")
    print(f"    table_09b: aggregate comparison")
    print(f"    table_09c: top {len(table_09c)} denied locations")


# ============================================================
# Data Bundle
# ============================================================

def generate_data_bundle():
    """Create a versioned ZIP of all charts, CSVs, map, and methodology."""
    import zipfile
    import glob as _glob
    from scripts_build_manifest import write_manifest
    version = DATA_BUNDLE_VERSION
    bundle_path = os.path.join(OUTPUT_DIR, f'data_bundle_v{version}.zip')
    root_bundle_path = f'data_bundle_v{version}.zip'
    write_manifest()
    curated = {
        'snapshot_window': f'{STUDY_START_YEAR}-{LAST_COMPLETE_YEAR}',
        'canonical_map': 'map_02_interactive_explorer.html',
        'map_data': 'map_data.json',
        'summary_charts': [
            {'file': 'chart_01d_denied_vs_approved.png', 'title': 'QCB5 Signal Study Outcomes: Denied and Approved'},
            {'file': 'chart_03b_signal_denial_rates.png', 'title': 'QCB5 and Citywide Signal Study Denial Rates by Year'},
            {'file': 'chart_03d_srts_denial_rates.png', 'title': 'QCB5 and Citywide Speed Bump Denial Rates by Year'},
            {'file': 'chart_05b_denial_reasons.png', 'title': 'QCB5 Speed Bump Denial Reasons'},
            {'file': 'chart_09_crash_proximity_analysis.png', 'title': 'Crash Proximity: Denied and Approved Signal Study Locations'},
            {'file': 'chart_15_srts_funnel.png', 'title': 'QCB5 DOT-Approved Speed Bumps: Post-Approval Outcomes'},
        ],
    }
    with open(os.path.join(OUTPUT_DIR, 'curated_charts.json'), 'w', encoding='utf-8') as cf:
        json.dump(curated, cf, indent=2)

    patterns = ['chart_*.png', 'table_*.csv', 'map_02_interactive_explorer.html',
                'map_data.json', 'curated_charts.json',
                'map_layer_*.csv', 'data_*.csv', 'geocode_cache_*.csv',
                'METHODOLOGY.md', 'source_manifest.json']
    with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for pattern in patterns:
            for f in sorted(_glob.glob(os.path.join(OUTPUT_DIR, pattern))):
                zf.write(f, os.path.basename(f))
    shutil.copyfile(bundle_path, root_bundle_path)
    n_files = sum(1 for _ in zipfile.ZipFile(bundle_path).namelist())
    print(f"  Data bundle saved: {bundle_path} ({n_files} files)")
    print(f"  Data bundle mirrored: {root_bundle_path}")


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("CB5 SAFETY ANALYSIS - MAP & CORRELATION GENERATION (Part 2)")
    print("=" * 60)

    # Load data
    data = load_and_prepare_data()

    # Step 1: Geocode signal studies
    print("\nStep 1: Geocoding signal study intersections...")
    signal_geo = geocode_signal_studies(data)

    # Step 2: Proximity analysis
    print("\nStep 2: Proximity analysis (150m radius)...")
    signal_prox, srts_prox = run_proximity_analysis(
        signal_geo, data['cb5_srts'], data['cb5_crashes'])

    # Print summary stats
    for label, df in [('Signal Studies', signal_prox), ('SRTS', srts_prox)]:
        denied = df[df['outcome'] == 'denied']
        approved = df[df['outcome'] == 'approved']
        print(f"\n  {label}:")
        print(f"    Denied:   median {denied['crashes_150m'].median():.0f} crashes, "
              f"{denied['injuries_150m'].median():.0f} injuries within 150m (n={len(denied)})")
        print(f"    Approved: median {approved['crashes_150m'].median():.0f} crashes, "
              f"{approved['injuries_150m'].median():.0f} injuries within 150m (n={len(approved)})")
        U, p = _mann_whitney_u(denied['crashes_150m'].dropna(), approved['crashes_150m'].dropna())
        print(f"    Mann-Whitney U: p={p:.6f}" + (" *" if p < 0.05 else ""))

    # Step 3: Prepare map layers and map_data.json (legacy Folium map_01 retired)
    print("\nStep 3: Preparing map layers and map_data.json...")
    before_after_df, search_entries, top15, top10_crashes, cb5_aps = prepare_map_layers(
        signal_prox, srts_prox, data['cb5_crashes'], data=data)

    # Save before-after analysis table
    if before_after_df is not None and len(before_after_df) > 0:
        ba_out = before_after_df.copy()
        ba_out['install_date'] = ba_out['install_date'].dt.strftime('%Y-%m-%d')
        ba_out['Source File'] = 'data_cb5_signal_studies.csv'
        ba_out.to_csv(f'{OUTPUT_DIR}/table_before_after_installed.csv', index=False)
        print(f"  Before-after table saved ({len(ba_out)} installed locations).")

    # Step 3b: Interactive explorer map
    print("\nStep 3b: Generating interactive explorer map...")
    map_interactive_explorer(signal_prox, srts_prox, data['cb5_crashes'], data,
                             before_after_df, search_entries, top15, top10_crashes, cb5_aps)

    # Step 4: Static charts
    print("\nStep 4: Generating charts...")
    chart_09_crash_proximity(signal_prox, srts_prox)
    chart_09b_top_denied_by_crashes(signal_prox)
    chart_09c_top_denied_by_injuries(signal_prox)
    chart_15_srts_funnel()

    # Step 5: Data tables
    print("\nStep 5: Saving data tables...")
    save_data_tables(signal_prox, srts_prox)

    # Step 6: Data bundle
    print("\nStep 6: Creating data bundle...")
    generate_data_bundle()

    print("\n" + "=" * 60)
    print("All Part 2 outputs saved to output/")
    print("=" * 60)


if __name__ == "__main__":
    main()
