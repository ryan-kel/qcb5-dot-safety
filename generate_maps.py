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
import folium
from folium.plugins import HeatMap, MarkerCluster
from shapely.geometry import shape, Point
from shapely.prepared import prep
import json
import warnings
import os
import math

warnings.filterwarnings('ignore')

# === CONFIGURATION ===
DATA_DIR = "data_raw"
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

GEOCODE_CACHE_PATH = f"{OUTPUT_DIR}/geocode_cache_signal_studies.csv"
CB5_BOUNDARY_PATH = f"{DATA_DIR}/cb5_boundary.geojson"
CB5_BOUNDARY_URL = "https://raw.githubusercontent.com/nycehs/NYC_geography/master/CD.geo.json"

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

# Color scheme — muted academic tones for print readability
COLORS = {
    'primary': '#2C5F8B',
    'citywide': '#B8860B',
    'denied': '#B44040',
    'approved': '#4A7C59',
    'crash': '#996633',
    'crash_alt': '#CC9966',
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
    html = '''<div class="map-title" id="map-title-container" style="position:fixed;top:10px;left:50%;
        transform:translateX(-50%);z-index:1000;background:rgba(255,255,255,0.92);
        padding:8px 20px;border:1px solid #666;
        font-family:'Times New Roman',Georgia,serif;text-align:center;">
        <div id="map-dynamic-title" style="font-size:15px;font-weight:bold;">Safety Request Outcomes: QCB5 (Queens Community Board 5)</div>
        <div id="map-dynamic-subtitle" style="font-size:11px;color:#555;margin-top:2px;">Signal Studies &amp; Speed Bumps vs. Injury Crashes (2020\u20132025)</div>
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
                subtitleEl.textContent = 'Signal Studies & Speed Bumps vs. Injury Crashes (2020\u20132025)';
            } else if (signals) {
                titleEl.textContent = 'Signal Study Outcomes: QCB5';
                subtitleEl.textContent = 'Traffic Signal & Stop Sign Requests vs. Crash Data';
            } else if (srts) {
                titleEl.textContent = 'Speed Bump Requests & Injury Crashes';
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


# Academic styling — matches generate_charts.py
plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Times New Roman', 'DejaVu Serif', 'Liberation Serif'],
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.titleweight': 'bold',
    'axes.labelsize': 11,
    'axes.labelweight': 'bold',
    'axes.spines.top': False,
    'axes.spines.right': False,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'legend.fontsize': 10,
    'figure.dpi': 150,
    'savefig.dpi': 300,
    'axes.grid': True,
    'grid.alpha': 0.3,
    'grid.linestyle': '--'
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

    # Filter SRTS to 2020–2025 for consistency with signal studies and crashes
    n_before_year = len(cb5_srts)
    cb5_srts = cb5_srts[cb5_srts['year'].between(2020, 2025)].copy()
    print(f"  CB5 SRTS: -> {len(cb5_srts):,} after 2020–2025 filter ({n_before_year - len(cb5_srts)} excluded)")

    # --- Crashes ---
    crashes['crash_date'] = pd.to_datetime(crashes['crash_date'], errors='coerce')
    crashes['year'] = crashes['crash_date'].dt.year
    crashes = crashes[crashes['year'].between(2020, 2025)]
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


def _build_srts_location_lookup(srts):
    """Build (street1, street2) -> (lat, lon) lookup from SRTS data."""
    df = srts[
        srts['fromlatitude'].notna() &
        srts['fromlongitude'].notna()
    ].copy()

    df['fromlatitude'] = pd.to_numeric(df['fromlatitude'], errors='coerce')
    df['fromlongitude'] = pd.to_numeric(df['fromlongitude'], errors='coerce')
    df = df[df['fromlatitude'].notna() & df['fromlongitude'].notna()]

    results = {}
    for _, row in df.iterrows():
        main = _normalize_street_name(row.get('onstreet', ''))
        from_st = _normalize_street_name(row.get('fromstreet', ''))
        to_st = _normalize_street_name(row.get('tostreet', ''))
        lat = row['fromlatitude']
        lon = row['fromlongitude']

        if main and from_st:
            key = tuple(sorted([main, from_st]))
            if key not in results:
                results[key] = (lat, lon)
        if main and to_st:
            key = tuple(sorted([main, to_st]))
            if key not in results:
                results[key] = (lat, lon)
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
            srts_lookup = _build_srts_location_lookup(data['srts'])
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
        geocoded = cache['latitude'].notna().sum()
        print(f"  Cache: {len(cache)} records, {geocoded} geocoded ({geocoded/len(cache)*100:.0f}%)")
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
    srts_lookup = _build_srts_location_lookup(data['srts'])
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
    cache_cols = ['referencenumber', 'mainstreet', 'crossstreet1', 'requesttype',
                  'statusdescription', 'outcome', 'year',
                  'daterequested', 'statusdate',
                  'latitude', 'longitude',
                  'geocode_tier', 'main_norm', 'cross_norm']
    cache_df = cb5_no_aps[[c for c in cache_cols if c in cb5_no_aps.columns]].copy()
    cache_df.to_csv(GEOCODE_CACHE_PATH, index=False)
    print(f"    Cache saved to {GEOCODE_CACHE_PATH}")

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

    # Handle ties: average ranks for tied values
    sorted_combined = combined[order]
    i = 0
    while i < len(sorted_combined):
        j = i + 1
        while j < len(sorted_combined) and sorted_combined[j] == sorted_combined[i]:
            j += 1
        if j > i + 1:
            avg_rank = np.mean(ranks[order[i:j]])
            for k in range(i, j):
                ranks[order[k]] = avg_rank
        i = j

    R1 = ranks[:n1].sum()
    U1 = R1 - n1 * (n1 + 1) / 2

    # Normal approximation for p-value
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sigma == 0:
        return U1, 1.0

    z = (U1 - mu) / sigma
    # Two-sided p-value via normal CDF approximation (Abramowitz & Stegun)
    az = abs(z)
    # Simple CDF approximation
    t = 1.0 / (1.0 + 0.2316419 * az)
    d = 0.3989422804014327  # 1/sqrt(2*pi)
    p_one = d * math.exp(-0.5 * az * az) * (
        t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    )
    p_two = 2 * p_one

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

    DATA_START = pd.Timestamp('2020-01-01')
    DATA_END = cb5_crashes['crash_date'].max()
    if pd.isna(DATA_END):
        DATA_END = pd.Timestamp('2025-12-31')

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
            'mainstreet': row['mainstreet'],
            'crossstreet1': row['crossstreet1'],
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
        _on = '' if pd.isna(r.get('on_street_name')) else str(r['on_street_name']).strip()
        _off = '' if pd.isna(r.get('off_street_name')) else str(r['off_street_name']).strip()
        _factor = str(r.get('contributing_factor_vehicle_1', '') or '').strip()
        _veh = str(r.get('vehicle_type_code1', '') or '').strip()
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
        main_st = str(row.get('mainstreet', '') or '')
        cross_st = str(row.get('crossstreet1', '') or '')
        req_type = str(row.get('requesttype', '') or '')
        status = str(row.get('statusdescription', '') or '').strip()
        findings = str(row.get('findings', '') or '').strip()
        school = str(row.get('schoolname', '') or '').strip()
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
        on_st = str(row.get('onstreet', '') or '')
        from_st = str(row.get('fromstreet', '') or '')
        to_st = str(row.get('tostreet', '') or '')
        proj_code = str(row.get('projectcode', '') or '')
        proj_status = str(row.get('projectstatus', '') or '').strip()
        denial = str(row.get('denialreason', '') or '').strip()
        direction = str(row.get('trafficdirectiondesc', '') or '').strip()
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
                'loc': str(r.get('location', '') or '').strip(),
                'nta': str(r.get('ntaname', '') or '').strip(),
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
                'main': str(ba.get('mainstreet', '')),
                'cross': str(ba.get('crossstreet1', '')),
                'type': str(ba.get('requesttype', '')),
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
    """Generate a lightweight interactive Leaflet map with year filtering and stats panel.

    NOT folium — vanilla Leaflet + MarkerCluster from CDN.
    Data embedded inline as JSON. ~1-1.5MB vs 14MB folium map.
    Output: output/map_02_interactive_explorer.html
    """
    print("  Generating interactive explorer map...")

    # Load pre-exported JSON data
    json_path = f'{OUTPUT_DIR}/map_data.json'
    with open(json_path) as f:
        map_data_str = f.read()

    html = _build_interactive_html(map_data_str)

    out_path = f'{OUTPUT_DIR}/map_02_interactive_explorer.html'
    with open(out_path, 'w') as f:
        f.write(html)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"    Interactive explorer map saved ({size_kb:.0f} KB)")


def _build_interactive_html(map_data_json_str):
    """Build the complete HTML for the interactive explorer map.

    Uses a 360px left sidebar panel (matching parking/citibike maps)
    with custom layer checkboxes instead of Leaflet's floating control.
    """

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QCB5 Safety Request Outcomes — Interactive Explorer</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<style>
:root {{
  --navy: #2C5F8B;
  --navy-dark: #1B3F5E;
  --gold: #B8860B;
  --red: #B44040;
  --green: #4A7C59;
  --crash: #996633;
  --aps: #7B68AE;
  --border: #e0e0e0;
  --font: Georgia, 'Times New Roman', serif;
}}
html, body {{ margin:0; padding:0; height:100%; font-family:var(--font); }}

/* Panel + Map layout */
.map-and-panel {{ display:flex; height:100vh; width:100%; }}

.panel {{
  width:360px; min-width:360px; height:100%;
  overflow-y:auto; background:#fff;
  border-right:1px solid var(--border);
  display:flex; flex-direction:column;
}}

.panel-header {{
  background:var(--navy-dark); color:#fff;
  padding:18px 20px 14px; text-align:center;
}}
.panel-header h1 {{ font-size:1.15rem; font-weight:700; letter-spacing:0.3px; margin-bottom:2px; }}
.panel-header .subtitle {{ font-size:0.82rem; opacity:0.75; font-style:italic; }}

.panel-section {{
  padding:14px 20px;
  border-bottom:1px solid var(--border);
}}

.section-title {{
  font-size:0.72rem; font-weight:600; text-transform:uppercase;
  letter-spacing:1px; color:var(--navy);
  margin-bottom:10px; padding-bottom:4px;
  border-bottom:1px solid var(--gold);
}}

/* Year filter bar (citibike pattern) */
.year-filter {{
  display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;
  padding:0.6rem 0.8rem; background:#f5f5f5;
  border:1px solid var(--border); border-radius:6px;
  font-size:0.9rem; margin-bottom:0.25rem;
}}
.year-filter label {{ font-weight:600; color:var(--navy); font-size:0.85rem; }}
.year-filter select {{
  font-family:var(--font); font-size:0.85rem;
  padding:4px 8px; border:1px solid var(--border);
  border-radius:4px; background:#fff;
}}
.year-filter select:focus {{ outline:none; border-color:var(--navy); }}
.year-filter .btn-apply {{
  font-family:var(--font); font-size:0.8rem;
  padding:4px 14px; border:1px solid var(--navy);
  background:var(--navy); color:#fff; border-radius:4px;
  cursor:pointer; font-weight:600;
}}
.year-filter .btn-apply:hover {{ opacity:0.9; }}
.year-filter .btn-reset {{
  font-family:var(--font); font-size:0.8rem;
  padding:4px 14px; border:1px solid var(--navy);
  background:none; border-radius:4px; cursor:pointer;
  color:var(--navy); font-weight:600;
}}
.year-filter .btn-reset:hover {{ background:var(--navy); color:#fff; }}

/* Layer toggles */
.layer-toggle {{
  display:flex; align-items:center; gap:6px;
  margin:4px 0; font-size:0.82rem; color:#2a2a2a; cursor:pointer;
}}
.layer-toggle input {{ margin:0; cursor:pointer; accent-color:var(--navy); }}
.layer-count {{ color:#888; font-size:0.75rem; font-variant-numeric:tabular-nums; }}
.layer-separator {{
  border:none; border-top:1px solid #f0f0f0;
  margin:6px 0;
}}

/* Legend */
.legend-item {{ display:block; margin:3px 0; font-size:0.78rem; color:#2a2a2a; }}
.legend-dot {{
  display:inline-block; width:10px; height:10px;
  border:1px solid #999; border-radius:50%;
  margin-right:6px; vertical-align:middle;
}}
.legend-spotlight {{
  display:inline-block; width:14px; height:14px; border-radius:50%;
  margin-right:5px; vertical-align:middle; position:relative;
}}
.legend-spotlight .inner {{
  position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
  width:5px; height:5px; border-radius:50%;
}}

/* Stats */
.stat-group {{ margin-bottom:8px; }}
.stat-group .stat-title {{
  font-weight:600; font-size:0.78rem; color:var(--navy-dark);
  margin-bottom:2px;
}}
.stat-row {{
  display:flex; justify-content:space-between; align-items:baseline;
  padding:2px 0; font-size:0.78rem;
  border-bottom:1px solid #f0f0f0;
}}
.stat-row:last-child {{ border-bottom:none; }}
.stat-denied {{ color:var(--red); font-weight:600; }}
.stat-approved {{ color:var(--green); font-weight:600; }}
.stat-crash {{ color:var(--crash); font-weight:600; }}
.stat-aps {{ color:var(--aps); font-weight:600; }}
.stat-value {{ font-weight:600; font-variant-numeric:tabular-nums; }}

/* Search */
.search-input-row {{ display:flex; gap:4px; }}
#ref-search {{
  flex:1; padding:5px 8px; font-family:var(--font);
  font-size:0.82rem; border:1px solid var(--border); border-radius:3px;
}}
#ref-search:focus {{ outline:none; border-color:var(--navy); }}
#ref-search-btn {{
  padding:5px 10px; font-family:var(--font); font-size:0.82rem;
  cursor:pointer; border:1px solid var(--border); background:#fff;
  border-radius:3px; color:var(--navy); font-weight:600;
}}
#ref-search-btn:hover {{ background:var(--navy); color:#fff; }}
#ref-search-msg {{ font-size:0.75rem; margin-top:4px; color:#888; }}
#ref-search-dropdown {{
  display:none; position:absolute; background:#fff; border:1px solid var(--border);
  max-height:180px; overflow-y:auto; width:calc(100% - 40px);
  font-size:0.78rem; z-index:1002; box-shadow:0 2px 6px rgba(0,0,0,0.1);
  border-radius:3px;
}}
.dropdown-item {{
  padding:5px 10px; cursor:pointer;
  border-bottom:1px solid #f0f0f0;
}}
.dropdown-item:hover {{ background:rgba(44,95,139,0.04); }}

/* Source citation */
.source-cite {{
  font-size:0.75rem; color:#888; font-style:italic;
  padding:10px 20px; border-top:1px solid var(--border);
  margin-top:auto;
}}
.source-cite a {{
  color:var(--navy); text-decoration:none;
  border-bottom:1px dotted var(--gold);
}}

/* Map container */
.map-wrapper {{ flex:1; min-width:0; position:relative; }}
#map {{ width:100%; height:100%; }}

/* Leaflet overrides */
.leaflet-popup-content-wrapper {{
  font-family:var(--font); font-size:0.82rem;
  border-radius:4px; box-shadow:0 2px 8px rgba(0,0,0,0.15);
}}
.leaflet-popup-tip-container {{ display:none; }}
.leaflet-popup-content {{ margin:10px 14px; font-size:12px; line-height:1.5; }}
.leaflet-popup-content b {{ font-size:13px; }}

/* Spotlight radius circles */
.leaflet-overlay-pane path[stroke-dasharray] {{ pointer-events:none !important; }}

/* Responsive */
@media (max-width: 768px) {{
  .map-and-panel {{ flex-direction:column-reverse; }}
  .panel {{
    width:100%; min-width:unset; height:auto;
    max-height:45vh; border-right:none;
    border-top:1px solid var(--border);
  }}
  .map-wrapper {{ height:55vh; }}
}}
</style>
</head>
<body>

<div class="map-and-panel">
  <div class="panel">
    <div class="panel-header">
      <h1 id="title-main">Safety Request Outcomes: QCB5</h1>
      <div class="subtitle" id="title-sub">Signal Studies &amp; Speed Bumps vs. Injury Crashes (2020&ndash;2025)</div>
    </div>

    <div class="panel-section" style="position:relative;">
      <div class="section-title">Search</div>
      <div class="search-input-row">
        <input id="ref-search" type="text" placeholder="Reference # (e.g. CQ21-0722)" autocomplete="off">
        <button id="ref-search-btn">Go</button>
      </div>
      <div id="ref-search-msg"></div>
      <div id="ref-search-dropdown"></div>
    </div>

    <div class="panel-section">
      <div class="section-title">Year Range</div>
      <div class="year-filter">
        <label>From</label>
        <select id="year-start">
          <option value="2020">2020</option>
          <option value="2021">2021</option><option value="2022">2022</option>
          <option value="2023">2023</option><option value="2024">2024</option>
          <option value="2025" selected>2025</option>
        </select>
        <label>To</label>
        <select id="year-end">
          <option value="2020">2020</option><option value="2021">2021</option>
          <option value="2022">2022</option><option value="2023">2023</option>
          <option value="2024">2024</option>
          <option value="2025" selected>2025</option>
        </select>
        <button class="btn-apply" id="year-apply">Apply</button>
        <button class="btn-reset" id="year-reset">Reset</button>
      </div>
    </div>

    <div class="panel-section">
      <div class="section-title">Layers</div>
      <label class="layer-toggle"><input type="checkbox" data-layer="deniedSignals" checked> Denied Signals <span class="layer-count" id="count-deniedSignals"></span></label>
      <label class="layer-toggle"><input type="checkbox" data-layer="approvedSignals" checked> Approved Signals <span class="layer-count" id="count-approvedSignals"></span></label>
      <label class="layer-toggle"><input type="checkbox" data-layer="deniedSrts" checked> Denied Speed Bumps <span class="layer-count" id="count-deniedSrts"></span></label>
      <label class="layer-toggle"><input type="checkbox" data-layer="approvedSrts" checked> Approved Speed Bumps <span class="layer-count" id="count-approvedSrts"></span></label>
      <label class="layer-toggle"><input type="checkbox" data-layer="aps"> APS Installed <span class="layer-count" id="count-aps"></span></label>
      <hr class="layer-separator">
      <label class="layer-toggle"><input type="checkbox" data-layer="crashDots" checked> Injury Crashes <span class="layer-count" id="count-crashDots"></span></label>
      <label class="layer-toggle"><input type="checkbox" data-layer="crashClustered"> Injury Crashes (clustered) <span class="layer-count" id="count-crashClustered"></span></label>
      <hr class="layer-separator">
      <label class="layer-toggle"><input type="checkbox" data-layer="top15"> Top 15 Denied Spotlight</label>
      <label class="layer-toggle"><input type="checkbox" data-layer="top10crashes"> Top 10 Crash Intersections</label>
      <label class="layer-toggle"><input type="checkbox" data-layer="effectiveness"> DOT Effectiveness <span class="layer-count" id="count-effectiveness"></span></label>
    </div>

    <div class="panel-section" id="legend-section">
      <div class="section-title">Legend</div>
      <span class="legend-item" data-layers="Denied Signal,Denied Speed"><span class="legend-dot" style="background:#B44040;"></span>Denied request</span>
      <span class="legend-item" data-layers="Approved Signal,Approved Speed"><span class="legend-dot" style="background:#4A7C59;"></span>Approved request</span>
      <span class="legend-item" data-layers="APS Installed"><span class="legend-dot" style="background:#7B68AE;"></span>APS installed</span>
      <span class="legend-item" data-layers="Injury Crashes"><span class="legend-dot" style="background:#888;"></span>Injury crash (dot = 1)</span>
      <span class="legend-item" data-layers="Injury Crashes"><span class="legend-dot" style="background:#1a1a1a;"></span>Fatal crash</span>
      <span class="legend-item" data-layers="Top 10 Crash"><span class="legend-spotlight" style="border:1.5px dashed #2C5F8B;"><span class="inner" style="background:#2C5F8B;"></span></span>Top 10 crash intersection</span>
      <span class="legend-item" data-layers="Top 15 Denied"><span class="legend-spotlight" style="border:1.5px dashed #B44040;"><span class="inner" style="background:#B44040;"></span></span>Top 15 denied spotlight</span>
      <span class="legend-item" data-layers="DOT Effectiveness"><span class="legend-spotlight" style="border:1.5px dashed #2d7d46;"><span class="inner" style="background:#2d7d46;"></span></span>Installed, decreased</span>
      <span class="legend-item" data-layers="DOT Effectiveness"><span class="legend-spotlight" style="border:1.5px dashed #cc8400;"><span class="inner" style="background:#cc8400;"></span></span>Installed, increased</span>
    </div>

    <div class="panel-section">
      <div class="section-title" id="stats-title">Statistics (2020&#8211;2025)</div>
      <div id="stats-body"></div>
    </div>

    <div class="source-cite">
      Sources: <a href="https://data.cityofnewyork.us/Transportation/DOT-Signal-Studies/w76s-c5u4" target="_blank" rel="noopener">DOT Signal Studies</a> &middot;
      <a href="https://data.cityofnewyork.us/Transportation/DOT-SRTS/9n6h-pt9g" target="_blank" rel="noopener">DOT SRTS</a> &middot;
      <a href="https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95" target="_blank" rel="noopener">Motor Vehicle Crashes</a>
    </div>
  </div>

  <div class="map-wrapper">
    <div id="map"></div>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
(function() {{
"use strict";

var DATA = {map_data_json_str};

var COLORS = {{denied:'#B44040',approved:'#4A7C59',crash:'#996633',primary:'#2C5F8B',aps:'#7B68AE'}};
var popupStyle = "font-family:Georgia,'Times New Roman',serif;font-size:12px;line-height:1.5;";
var hr = "<hr style='border:0;border-top:1px solid #eee;margin:4px 0;'>";

// Current year range
var yearStart = 2025, yearEnd = 2025;

// Map
var map = L.map('map', {{center:[40.714,-73.889], zoom:14, zoomControl:false}});
L.control.zoom({{position:'bottomright'}}).addTo(map);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_nolabels/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution:'&copy; OpenStreetMap &copy; CARTO', maxZoom:19
}}).addTo(map);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_only_labels/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  maxZoom:19, opacity:0.55, pane:'overlayPane'
}}).addTo(map);

// CB5 boundary
if (DATA.boundary && DATA.boundary.features) {{
  L.geoJSON(DATA.boundary, {{
    style: {{color:'#555',weight:2,opacity:0.6,fillColor:'#555',fillOpacity:0.02,dashArray:'6 3',interactive:false}}
  }}).addTo(map);
}}

// === Index data by year ===
var dataByYear = {{}};
function indexByYear(key, arr) {{
  dataByYear[key] = {{}};
  arr.forEach(function(r) {{
    var y = r.y || 0;
    if (!dataByYear[key][y]) dataByYear[key][y] = [];
    dataByYear[key][y].push(r);
  }});
}}
indexByYear('crashes', DATA.crashes);
indexByYear('deniedSignals', DATA.deniedSignals);
indexByYear('approvedSignals', DATA.approvedSignals);
indexByYear('deniedSrts', DATA.deniedSrts);
indexByYear('approvedSrts', DATA.approvedSrts);
indexByYear('aps', DATA.aps);

function getRecordsInRange(key) {{
  var out = [];
  var idx = dataByYear[key] || {{}};
  for (var y = yearStart; y <= yearEnd; y++) {{
    if (idx[y]) out = out.concat(idx[y]);
  }}
  return out;
}}

// === Layer builders ===
var layerGroups = {{}};

function crashPopup(r) {{
  var loc = (r.on && r.off) ? r.on+' & '+r.off : (r.on || r.off || 'Location on map');
  var sev = r.k>0?'<span style="color:#B44040;font-weight:bold;">FATAL</span>'
           :r.inj>0?'<span style="color:#cc8400;font-weight:bold;">INJURY</span>':'Property damage';
  return '<div style="'+popupStyle+'"><b>'+loc+'</b><br>'+r.dt+' at '+r.tm+'<br>Severity: '+sev
    +hr+'Pedestrians: '+r.pinj+' injured, '+r.pk+' killed<br>Cyclists: '+r.cinj+' injured, '
    +r.ck+' killed<br>Motorists: '+r.minj+' injured, '+r.mk+' killed'
    +hr+'Factor: '+(r.fac||'N/A')+'<br>Vehicle: '+(r.veh||'N/A')
    +'<br><span style="color:#666;font-size:10px;">Collision ID: '+r.cid+'</span></div>';
}}

function buildCrashDots(records) {{
  var fg = L.featureGroup();
  records.forEach(function(r) {{
    var rad, color, opacity;
    if (r.k>0) {{ rad=3.5; color='#1a1a1a'; opacity=0.8; }}
    else if (r.inj>0) {{ rad=1.8; color='#888'; opacity=0.35; }}
    else {{ rad=1.2; color='#aaa'; opacity=0.2; }}
    var sev = r.k>0?'Fatal':(r.inj>0?r.inj+' injured':'Crash');
    var loc = (r.on&&r.off)?r.on+' & '+r.off:(r.on||r.off||'');
    L.circleMarker([r.jlat, r.jlon], {{radius:rad,color:color,fillColor:color,
      fillOpacity:opacity,weight:0.3}})
      .bindPopup(crashPopup(r),{{maxWidth:320}})
      .bindTooltip(loc+' — '+sev+', '+r.dt)
      .addTo(fg);
  }});
  return fg;
}}

function buildCrashClustered(records) {{
  var cluster = L.markerClusterGroup({{
    maxClusterRadius:25, spiderfyOnMaxZoom:true,
    showCoverageOnHover:false, zoomToBoundsOnClick:true,
    spiderfyDistanceMultiplier:1.5,
    iconCreateFunction:function(cl) {{
      var c=cl.getChildCount(), sz=c<10?26:c<50?32:38;
      return L.divIcon({{
        html:'<div style="background:rgba(44,95,139,0.82);color:white;font-weight:bold;'
          +'font-family:Georgia,serif;font-size:11px;text-align:center;line-height:'
          +sz+'px;border-radius:50%;border:2px solid rgba(184,134,11,0.6);">'+c+'</div>',
        className:'',iconSize:L.point(sz,sz)
      }});
    }}
  }});
  records.forEach(function(r) {{
    var d = r.k>0?6:r.inj>0?5:4;
    var color = r.k>0?'#1a1a1a':r.inj>0?'#888':'#aaa';
    var opacity = r.k>0?0.8:r.inj>0?0.35:0.2;
    var icon = L.divIcon({{html:'<div style="width:'+d+'px;height:'+d+'px;background:'+color
      +';border-radius:50%;opacity:'+opacity+';"></div>',className:'',iconSize:L.point(d,d),
      iconAnchor:L.point(d/2,d/2)}});
    var sev = r.k>0?'Fatal':(r.inj>0?r.inj+' injured':'Crash');
    var loc = (r.on&&r.off)?r.on+' & '+r.off:(r.on||r.off||'');
    L.marker([r.lat,r.lon],{{icon:icon}})
      .bindPopup(crashPopup(r),{{maxWidth:320}})
      .bindTooltip(loc+' — '+sev+', '+r.dt)
      .addTo(cluster);
  }});
  return cluster;
}}

function signalPopup(r) {{
  var loc = r.main+' & '+r.cross;
  var oc = r.outcome==='denied'?'DENIED':'APPROVED';
  var ocColor = r.outcome==='denied'?COLORS.denied:COLORS.approved;
  var extras = '';
  if (r.school) extras+='School: '+r.school+'<br>';
  if (r.vz) extras+='Vision Zero priority: Yes<br>';
  if (r.findings) extras+='Findings: '+r.findings+'<br>';
  return '<div style="'+popupStyle+'"><b>'+loc+'</b><br>'
    +'<span style="color:#666;font-size:10px;">'+r.ref+'</span><br>'
    +'Type: '+r.type+'<br>'
    +'Outcome: <span style="color:'+ocColor+';font-weight:bold;">'+oc+'</span>'
    +hr+'Requested: '+r.reqDt+'<br>Status date: '+r.statusDt+'<br>Status: '+r.status
    +hr+extras+'<b>Within 150m (2020\\u20132025):</b><br>'
    +'Crashes: '+r.cr+'<br>Injuries: '+r.inj+'<br>Ped. injuries: '+r.pinj+'<br>Fatalities: '+r.fat+'</div>';
}}

function buildSignalLayer(records, outcome) {{
  var fg = L.featureGroup();
  var fillColor = outcome==='denied'?COLORS.denied:COLORS.approved;
  records.forEach(function(r) {{
    var loc = r.main+' & '+r.cross;
    L.circleMarker([r.lat,r.lon],{{radius:5,color:'#333',fillColor:fillColor,
      fillOpacity:0.75,weight:1}})
      .bindPopup(signalPopup(r),{{maxWidth:340}})
      .bindTooltip(loc+' — '+r.type+' ('+(outcome==='denied'?'DENIED':'APPROVED')+')')
      .addTo(fg);
  }});
  return fg;
}}

function srtsPopup(r) {{
  var oc = r.outcome==='denied'?'DENIED':'APPROVED';
  var ocColor = r.outcome==='denied'?COLORS.denied:COLORS.approved;
  var extras = '';
  if (r.denial) extras+='Denial reason: '+r.denial+'<br>';
  if (r.installDt) extras+='Installed: '+r.installDt+'<br>';
  if (r.dir) extras+='Traffic: '+r.dir+'<br>';
  return '<div style="'+popupStyle+'"><b>'+r.on+'</b> ('+r.from+' to '+r.to+')<br>'
    +'<span style="color:#666;font-size:10px;">'+r.code+'</span><br>'
    +'Outcome: <span style="color:'+ocColor+';font-weight:bold;">'+oc+'</span>'
    +hr+'Requested: '+r.reqDt+'<br>Decision date: '+r.closedDt+'<br>Project status: '+r.projStatus
    +hr+extras+'<b>Within 150m (2020\\u20132025):</b><br>'
    +'Crashes: '+r.cr+'<br>Injuries: '+r.inj+'<br>Ped. injuries: '+r.pinj+'<br>Fatalities: '+r.fat+'</div>';
}}

function buildSrtsLayer(records, outcome) {{
  var fg = L.featureGroup();
  var fillColor = outcome==='denied'?COLORS.denied:COLORS.approved;
  records.forEach(function(r) {{
    L.circleMarker([r.lat,r.lon],{{radius:5,color:'#333',fillColor:fillColor,
      fillOpacity:0.75,weight:1}})
      .bindPopup(srtsPopup(r),{{maxWidth:340}})
      .bindTooltip(r.on+' ('+r.from+' to '+r.to+') — '+(outcome==='denied'?'DENIED':'APPROVED'))
      .addTo(fg);
  }});
  return fg;
}}

function buildApsLayer(records) {{
  var fg = L.featureGroup();
  records.forEach(function(r) {{
    var popup = '<div style="'+popupStyle+'"><b>'+r.loc+'</b><br>'
      +'<span style="color:#7B68AE;font-weight:bold;">APS INSTALLED</span>'
      +hr+'Installed: '+r.dt+'<br>Neighborhood: '+r.nta
      +hr+'<span style="color:#666;font-size:10px;">Source: APS Installed Locations [de3m-c5p4]<br>'
      +'Court-mandated (federal ADA lawsuit).<br>'
      +'Excluded from merit-based approval rate analysis.</span></div>';
    L.circleMarker([r.lat,r.lon],{{radius:5,color:'#333',fillColor:'#7B68AE',
      fillOpacity:0.75,weight:1}})
      .bindPopup(popup,{{maxWidth:300}})
      .bindTooltip(r.loc+' — APS Installed '+r.dt)
      .addTo(fg);
  }});
  return fg;
}}

// === Dynamic layers (recomputed on year filter change) ===

function haversineDist(lat1, lon1, lat2, lon2) {{
  var R = 6371000;
  var dLat = (lat2-lat1)*Math.PI/180;
  var dLon = (lon2-lon1)*Math.PI/180;
  var a = Math.sin(dLat/2)*Math.sin(dLat/2)
    + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)
    * Math.sin(dLon/2)*Math.sin(dLon/2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}}

function buildEffectivenessLayer() {{
  var fg = L.featureGroup();
  if (!DATA.effectiveness) return fg;
  DATA.effectiveness.forEach(function(ba) {{
    var instYear = ba.installDt ? parseInt(ba.installDt.split(', ').pop()) : 0;
    if (instYear < yearStart || instYear > yearEnd) return;
    var fillColor, outline, label;
    if (ba.chg<0) {{ fillColor='#2d7d46'; outline='#1a5c2e'; label=Math.abs(Math.round(ba.pct))+'% fewer crashes'; }}
    else if (ba.chg===0) {{ fillColor='#777'; outline='#555'; label='No change'; }}
    else {{ fillColor='#cc8400'; outline='#996300'; label=Math.round(ba.pct)+'% more crashes'; }}
    var injChg = ba.ai-ba.bi;
    var injPct = ba.bi>0?Math.round(injChg/ba.bi*100):0;
    var injLabel = injChg<0?Math.abs(injPct)+'% fewer':(injChg>0?injPct+'% more':'No change');
    var mr = Math.max(7, Math.min(14, 5+ba.bc));
    var popup = '<div style="'+popupStyle+'"><b>'+ba.main+' & '+ba.cross+'</b><br>'
      +'<span style="color:#666;font-size:10px;">'+ba.ref+'</span><br>'
      +'Type: '+ba.type+'<br>Requested: '+ba.reqDt+'<br>Installed: '+ba.installDt
      +hr+'<b>Before-After Analysis</b> ('+ba.wm+'-mo. windows, 150m):<br>'
      +'Crashes: '+ba.bc+' &rarr; '+ba.ac+' (<b style="color:'+fillColor+';">'+label+'</b>)<br>'
      +'Injuries: '+ba.bi+' &rarr; '+ba.ai+' ('+injLabel+')</div>';
    L.circle([ba.lat,ba.lon],{{radius:150,color:fillColor,fillColor:fillColor,
      fillOpacity:0.08,weight:1.5,dashArray:'5 3',interactive:false}}).addTo(fg);
    L.circleMarker([ba.lat,ba.lon],{{radius:mr,color:outline,fillColor:fillColor,
      fillOpacity:0.8,weight:2}})
      .bindPopup(popup,{{maxWidth:320}})
      .bindTooltip(ba.main+' & '+ba.cross+' — '+label)
      .addTo(fg);
  }});
  return fg;
}}

function countEffectiveness() {{
  var n = 0;
  (DATA.effectiveness||[]).forEach(function(ba) {{
    var instYear = ba.installDt ? parseInt(ba.installDt.split(', ').pop()) : 0;
    if (instYear >= yearStart && instYear <= yearEnd) n++;
  }});
  return n;
}}

function buildTop15Layer(crashes, deniedSigs, deniedSrts) {{
  var fg = L.featureGroup();
  if (crashes.length === 0) return fg;
  var locs = [];
  deniedSigs.forEach(function(d) {{
    if (!d.lat || !d.lon) return;
    locs.push({{lat:d.lat,lon:d.lon,name:d.main+' & '+d.cross,dataset:'Signal Study',type:d.type}});
  }});
  deniedSrts.forEach(function(d) {{
    if (!d.lat || !d.lon) return;
    locs.push({{lat:d.lat,lon:d.lon,name:d.on+' ('+d.from+' to '+d.to+')',dataset:'Speed Bump',type:'Speed Reducer'}});
  }});
  if (locs.length === 0) return fg;
  var dLat = 0.00135, dLon = 0.0018;
  locs.forEach(function(loc) {{
    var cr=0, inj=0, pinj=0, fat=0;
    crashes.forEach(function(c) {{
      if (Math.abs(c.lat-loc.lat)>dLat || Math.abs(c.lon-loc.lon)>dLon) return;
      if (haversineDist(loc.lat,loc.lon,c.lat,c.lon) <= 150) {{
        cr++; inj+=c.inj; pinj+=c.pinj; fat+=c.k;
      }}
    }});
    loc.cr=cr; loc.inj=inj; loc.pinj=pinj; loc.fat=fat;
  }});
  locs.sort(function(a,b) {{ return b.cr-a.cr; }});
  var selected = [];
  locs.forEach(function(loc) {{
    if (selected.length >= 15) return;
    var tooClose = false;
    for (var i=0; i<selected.length; i++) {{
      if (haversineDist(loc.lat,loc.lon,selected[i].lat,selected[i].lon) < 150) {{ tooClose=true; break; }}
    }}
    if (!tooClose) selected.push(loc);
  }});
  selected.forEach(function(r, idx) {{
    var rank = idx+1;
    L.circle([r.lat,r.lon],{{radius:150,color:COLORS.denied,fillColor:COLORS.denied,
      fillOpacity:0.08,weight:1.5,dashArray:'5 3',interactive:false}}).addTo(fg);
    var popup = '<div style="'+popupStyle+'"><b>#'+rank+': '+r.name+'</b><br>'
      +'Dataset: '+r.dataset+'<br>Request: '+r.type
      +hr+'<b>Within 150m:</b><br>Crashes: '+r.cr+'<br>Injuries: '+r.inj
      +'<br>Ped. injuries: '+r.pinj+'<br>Fatalities: '+r.fat+'</div>';
    L.circleMarker([r.lat,r.lon],{{radius:9,color:'#333',fillColor:COLORS.denied,
      fillOpacity:0.85,weight:2}})
      .bindPopup(popup,{{maxWidth:300}})
      .bindTooltip('#'+rank+': '+r.name+' ('+r.cr+' crashes)')
      .addTo(fg);
    L.marker([r.lat,r.lon],{{icon:L.divIcon({{
      html:'<div style="font-family:Georgia,serif;font-size:10px;font-weight:bold;'
        +'color:white;text-align:center;margin-top:-5px;pointer-events:none;">'+rank+'</div>',
      className:'',iconSize:L.point(20,20),iconAnchor:L.point(10,10)}}),
      interactive:false}}).addTo(fg);
  }});
  return fg;
}}

function buildTop10CrashLayer(crashes) {{
  var fg = L.featureGroup();
  if (crashes.length === 0) return fg;
  var byInt = {{}};
  crashes.forEach(function(c) {{
    if (!c.on || !c.off) return;
    var parts = [c.on, c.off].sort();
    var key = parts[0]+' & '+parts[1];
    if (!byInt[key]) byInt[key] = {{lat:c.lat,lon:c.lon,cr:0,inj:0,pinj:0,cinj:0,fat:0}};
    byInt[key].cr++;
    byInt[key].inj += c.inj;
    byInt[key].pinj += c.pinj;
    byInt[key].cinj += (c.cinj||0);
    byInt[key].fat += c.k;
  }});
  var ints = Object.keys(byInt).sort(function(a,b) {{ return byInt[b].cr - byInt[a].cr; }}).slice(0,10);
  ints.forEach(function(name, idx) {{
    var cr = byInt[name];
    var rank = idx+1;
    L.circle([cr.lat,cr.lon],{{radius:150,color:COLORS.primary,fillColor:COLORS.primary,
      fillOpacity:0.08,weight:1.5,dashArray:'5 3',interactive:false}}).addTo(fg);
    var popup = '<div style="'+popupStyle+'"><b>#'+rank+': '+name+'</b>'
      +hr+'<b>Crashes:</b> '+cr.cr+'<br><b>Total injuries:</b> '+cr.inj
      +'<br>Pedestrian: '+cr.pinj+'<br>Cyclist: '+cr.cinj+'<br><b>Fatalities:</b> '+cr.fat+'</div>';
    L.circleMarker([cr.lat,cr.lon],{{radius:9,color:'#333',fillColor:COLORS.primary,
      fillOpacity:0.85,weight:2}})
      .bindPopup(popup,{{maxWidth:300}})
      .bindTooltip('#'+rank+': '+name+' ('+cr.cr+' crashes)')
      .addTo(fg);
    L.marker([cr.lat,cr.lon],{{icon:L.divIcon({{
      html:'<div style="font-family:Georgia,serif;font-size:10px;font-weight:bold;'
        +'color:white;text-align:center;margin-top:-5px;pointer-events:none;">'+rank+'</div>',
      className:'',iconSize:L.point(20,20),iconAnchor:L.point(10,10)}}),
      interactive:false}}).addTo(fg);
  }});
  return fg;
}}

// === Build all layers ===
var yearRange = yearStart===yearEnd ? String(yearStart) : yearStart+'\\u2013'+yearEnd;
var crashRecs = getRecordsInRange('crashes');
var denSigRecs = getRecordsInRange('deniedSignals');
var appSigRecs = getRecordsInRange('approvedSignals');
var denSrtsRecs = getRecordsInRange('deniedSrts');
var appSrtsRecs = getRecordsInRange('approvedSrts');
var apsRecs = getRecordsInRange('aps');

layerGroups.crashDots = buildCrashDots(crashRecs);
layerGroups.crashClustered = buildCrashClustered(crashRecs);
layerGroups.deniedSignals = buildSignalLayer(denSigRecs, 'denied');
layerGroups.approvedSignals = buildSignalLayer(appSigRecs, 'approved');
layerGroups.deniedSrts = buildSrtsLayer(denSrtsRecs, 'denied');
layerGroups.approvedSrts = buildSrtsLayer(appSrtsRecs, 'approved');
layerGroups.aps = buildApsLayer(apsRecs);
layerGroups.effectiveness = buildEffectivenessLayer();
layerGroups.top15 = buildTop15Layer(crashRecs, denSigRecs, denSrtsRecs);
layerGroups.top10crashes = buildTop10CrashLayer(crashRecs);

// Layer display names (used for title logic)
var layerNames = {{
  crashDots: 'Injury Crashes',
  crashClustered: 'Injury Crashes',
  deniedSignals: 'Denied Signal Studies',
  approvedSignals: 'Approved Signal Studies',
  deniedSrts: 'Denied Speed Bumps',
  approvedSrts: 'Approved Speed Bumps',
  aps: 'APS Installed',
  effectiveness: 'DOT Effectiveness',
  top15: 'Top 15 Denied Spotlight',
  top10crashes: 'Top 10 Crash Intersections',
}};

// Default-on layers
var defaultOn = ['crashDots','deniedSignals','approvedSignals','deniedSrts','approvedSrts'];
defaultOn.forEach(function(k) {{ layerGroups[k].addTo(map); }});

// === Custom layer toggle (sidebar checkboxes) ===
function updateLayerCounts() {{
  var counts = {{
    crashDots: crashRecs.length,
    crashClustered: crashRecs.length,
    deniedSignals: denSigRecs.length,
    approvedSignals: appSigRecs.length,
    deniedSrts: denSrtsRecs.length,
    approvedSrts: appSrtsRecs.length,
    aps: apsRecs.length,
    effectiveness: countEffectiveness(),
  }};
  for (var k in counts) {{
    var el = document.getElementById('count-'+k);
    if (el) el.textContent = '('+counts[k].toLocaleString()+')';
  }}
}}
updateLayerCounts();

// Wire up checkboxes
document.querySelectorAll('.layer-toggle input[data-layer]').forEach(function(cb) {{
  cb.addEventListener('change', function() {{
    var key = this.getAttribute('data-layer');
    if (!layerGroups[key]) return;
    if (this.checked) {{
      layerGroups[key].addTo(map);
    }} else {{
      map.removeLayer(layerGroups[key]);
    }}
    updateTitle();
    updateLegend();
  }});
}});

// === Year filter logic ===
var selStart = document.getElementById('year-start');
var selEnd = document.getElementById('year-end');

function enforceYearRange() {{
  var s = parseInt(selStart.value), e = parseInt(selEnd.value);
  if (s > e) selEnd.value = selStart.value;
}}

function rebuildYearLayers() {{
  yearStart = parseInt(selStart.value);
  yearEnd = parseInt(selEnd.value);
  yearRange = yearStart+'\\u2013'+yearEnd;

  // Track which layers were on the map via checkboxes
  var wasChecked = {{}};
  document.querySelectorAll('.layer-toggle input[data-layer]').forEach(function(cb) {{
    wasChecked[cb.getAttribute('data-layer')] = cb.checked;
  }});

  // Remove old layers from map
  for (var k in layerGroups) {{
    if (map.hasLayer(layerGroups[k])) map.removeLayer(layerGroups[k]);
  }}

  // Rebuild year-filterable layers
  crashRecs = getRecordsInRange('crashes');
  denSigRecs = getRecordsInRange('deniedSignals');
  appSigRecs = getRecordsInRange('approvedSignals');
  denSrtsRecs = getRecordsInRange('deniedSrts');
  appSrtsRecs = getRecordsInRange('approvedSrts');
  apsRecs = getRecordsInRange('aps');

  layerGroups.crashDots = buildCrashDots(crashRecs);
  layerGroups.crashClustered = buildCrashClustered(crashRecs);
  layerGroups.deniedSignals = buildSignalLayer(denSigRecs, 'denied');
  layerGroups.approvedSignals = buildSignalLayer(appSigRecs, 'approved');
  layerGroups.deniedSrts = buildSrtsLayer(denSrtsRecs, 'denied');
  layerGroups.approvedSrts = buildSrtsLayer(appSrtsRecs, 'approved');
  layerGroups.aps = buildApsLayer(apsRecs);
  layerGroups.effectiveness = buildEffectivenessLayer();
  layerGroups.top15 = buildTop15Layer(crashRecs, denSigRecs, denSrtsRecs);
  layerGroups.top10crashes = buildTop10CrashLayer(crashRecs);

  // Re-add layers that were checked
  for (var k in wasChecked) {{
    if (wasChecked[k] && layerGroups[k]) layerGroups[k].addTo(map);
  }}

  updateLayerCounts();
  updateStats();
  updateTitle();
  updateLegend();
  notifyParentYear();
}}

selStart.addEventListener('change', function() {{ enforceYearRange(); }});
selEnd.addEventListener('change', function() {{ enforceYearRange(); }});
document.getElementById('year-apply').addEventListener('click', function() {{
  enforceYearRange(); rebuildYearLayers();
}});
document.getElementById('year-reset').addEventListener('click', function() {{
  selStart.value = '2020'; selEnd.value = '2025'; rebuildYearLayers();
}});

// === Stats panel ===
function updateStats() {{
  document.getElementById('stats-title').textContent = 'Statistics ('+yearRange+')';
  var html = '';
  html += '<div class="stat-group"><div class="stat-title">Signal Studies</div>';
  html += '<div class="stat-row"><span>Denied</span><span class="stat-denied">'+denSigRecs.length+'</span></div>';
  html += '<div class="stat-row"><span>Approved</span><span class="stat-approved">'+appSigRecs.length+'</span></div>';
  var sigTotal = denSigRecs.length+appSigRecs.length;
  var sigRate = sigTotal>0?(appSigRecs.length/sigTotal*100).toFixed(1):'0.0';
  html += '<div class="stat-row"><span>Approval rate</span><span class="stat-value">'+sigRate+'%</span></div></div>';
  html += '<div class="stat-group"><div class="stat-title">Speed Bumps</div>';
  html += '<div class="stat-row"><span>Denied</span><span class="stat-denied">'+denSrtsRecs.length+'</span></div>';
  html += '<div class="stat-row"><span>Approved</span><span class="stat-approved">'+appSrtsRecs.length+'</span></div>';
  var srtsTotal = denSrtsRecs.length+appSrtsRecs.length;
  var srtsRate = srtsTotal>0?(appSrtsRecs.length/srtsTotal*100).toFixed(1):'0.0';
  html += '<div class="stat-row"><span>Approval rate</span><span class="stat-value">'+srtsRate+'%</span></div></div>';
  var totInj=0, totPedInj=0, totFat=0;
  crashRecs.forEach(function(r){{ totInj+=r.inj; totPedInj+=r.pinj; totFat+=r.k; }});
  html += '<div class="stat-group"><div class="stat-title">Crashes</div>';
  html += '<div class="stat-row"><span>Total</span><span class="stat-crash">'+crashRecs.length.toLocaleString()+'</span></div>';
  html += '<div class="stat-row"><span>Injuries</span><span>'+totInj.toLocaleString()+'</span></div>';
  html += '<div class="stat-row"><span>Ped. injuries</span><span>'+totPedInj.toLocaleString()+'</span></div>';
  html += '<div class="stat-row"><span>Fatalities</span><span>'+totFat.toLocaleString()+'</span></div></div>';
  html += '<div class="stat-group"><div class="stat-title">APS Installed</div>';
  html += '<div class="stat-row"><span>Count</span><span class="stat-aps">'+apsRecs.length+'</span></div></div>';
  document.getElementById('stats-body').innerHTML = html;
}}
updateStats();

// === Dynamic title ===
function isLayerActive(prefix) {{
  for (var k in layerNames) {{
    if (layerNames[k].indexOf(prefix)===0 && map.hasLayer(layerGroups[k])) return true;
  }}
  return false;
}}

function updateTitle() {{
  var titleEl = document.getElementById('title-main');
  var subEl = document.getElementById('title-sub');
  var yr = yearRange;
  if (isLayerActive('DOT Effectiveness')) {{
    titleEl.textContent = 'DOT Effectiveness: Crash Outcomes After Installation';
    subEl.textContent = 'Before-After Analysis, Confirmed Installations, QCB5';
  }} else if (isLayerActive('Top 10 Crash')) {{
    titleEl.textContent = 'Top 10 Crash Intersections: QCB5';
    subEl.textContent = 'Highest Crash-Frequency Intersections (2020\\u20132025)';
  }} else if (isLayerActive('Top 15 Denied')) {{
    titleEl.textContent = 'Top 15 Denied Locations by Nearby Crash Count';
    subEl.textContent = '150m Analysis Radius, QCB5';
  }} else if ((isLayerActive('Denied Signal')||isLayerActive('Approved Signal'))
    && (isLayerActive('Denied Speed')||isLayerActive('Approved Speed'))) {{
    titleEl.textContent = 'Safety Request Outcomes: QCB5';
    subEl.textContent = 'Signal Studies & Speed Bumps vs. Injury Crashes ('+yr+')';
  }} else if (isLayerActive('Denied Signal')||isLayerActive('Approved Signal')) {{
    titleEl.textContent = 'Signal Study Outcomes: QCB5';
    subEl.textContent = 'Traffic Signal & Stop Sign Requests vs. Crash Data ('+yr+')';
  }} else if (isLayerActive('Denied Speed')||isLayerActive('Approved Speed')) {{
    titleEl.textContent = 'Speed Bump Requests & Injury Crashes';
    subEl.textContent = 'SRTS Program, QCB5 ('+yr+')';
  }} else {{
    titleEl.textContent = 'Safety Infrastructure Data: QCB5';
    subEl.textContent = 'Use layer controls to explore';
  }}
}}

// === Legend visibility ===
function updateLegend() {{
  var anyVisible = false;
  document.querySelectorAll('.legend-item').forEach(function(el) {{
    var prefixes = el.getAttribute('data-layers').split(',');
    var show = prefixes.some(function(p) {{ return isLayerActive(p.trim()); }});
    el.style.display = show?'block':'none';
    if (show) anyVisible = true;
  }});
  document.getElementById('legend-section').style.display = anyVisible?'':'none';
}}

updateTitle();
updateLegend();

// === Search ===
var SEARCH_INDEX = DATA.searchIndex || {{}};
var allRefs = Object.keys(SEARCH_INDEX);
var highlightLayer = null, highlightTimeout = null;

function clearHighlight() {{
  if (highlightLayer) {{ try{{ highlightLayer.remove(); }}catch(e){{}} highlightLayer=null; }}
  if (highlightTimeout) {{ clearTimeout(highlightTimeout); highlightTimeout=null; }}
}}

function normalizeRef(s) {{ return s.replace(/[-\\s]/g,'').toUpperCase(); }}

function fuzzyFind(ref) {{
  if (SEARCH_INDEX[ref]) return ref;
  var nq = normalizeRef(ref);
  for (var i=0;i<allRefs.length;i++) {{ if (normalizeRef(allRefs[i])===nq) return allRefs[i]; }}
  for (var i=0;i<allRefs.length;i++) {{ if (normalizeRef(allRefs[i]).indexOf(nq)>=0) return allRefs[i]; }}
  return null;
}}

function doSearch(ref) {{
  ref = ref.trim().toUpperCase();
  var msg = document.getElementById('ref-search-msg');
  var found = fuzzyFind(ref);
  if (!found) {{ msg.style.color='#B44040'; msg.textContent='Not found: '+ref; return; }}
  ref = found;
  var entry = SEARCH_INDEX[ref];
  document.getElementById('ref-search').value = ref;
  msg.style.color='#4A7C59';
  msg.textContent = entry.label+' ('+entry.outcome+')';
  clearHighlight();
  map.setView([entry.lat, entry.lon], 17);
  highlightLayer = L.layerGroup();
  var ring = L.circleMarker([entry.lat, entry.lon], {{
    radius:18, color:'#B8860B', weight:3, fill:false, opacity:0.9
  }});
  ring.addTo(highlightLayer);
  L.popup({{offset:[0,-8]}}).setLatLng([entry.lat, entry.lon])
    .setContent('<div style="font-family:Georgia,serif;font-size:12px;">'
      +'<b>'+entry.label+'</b><br>'+ref+'<br>Type: '+(entry.type||'N/A')
      +'<br>Outcome: <b>'+entry.outcome+'</b></div>')
    .addTo(highlightLayer);
  highlightLayer.addTo(map);
  var grow=true;
  var pulseInt = setInterval(function() {{
    if (!highlightLayer){{ clearInterval(pulseInt); return; }}
    ring.setRadius(grow?24:18); ring.setStyle({{opacity:grow?0.5:0.9}}); grow=!grow;
  }}, 600);
  highlightTimeout = setTimeout(function() {{ clearHighlight(); clearInterval(pulseInt); }}, 8000);
  map.once('click', function() {{ clearHighlight(); clearInterval(pulseInt); }});
}}

function showDropdown(query) {{
  var dd = document.getElementById('ref-search-dropdown');
  if (!query || query.length<2) {{ dd.style.display='none'; return; }}
  var uq = query.toUpperCase(), nq = normalizeRef(query);
  var matches = allRefs.filter(function(r) {{
    return r.indexOf(uq)>=0 || normalizeRef(r).indexOf(nq)>=0;
  }}).slice(0,10);
  if (matches.length===0) {{ dd.style.display='none'; return; }}
  dd.innerHTML='';
  matches.forEach(function(ref) {{
    var entry = SEARCH_INDEX[ref];
    var div = document.createElement('div');
    div.className = 'dropdown-item';
    div.textContent = ref+' \\u2014 '+(entry.label||'');
    div.onclick = function(){{
      document.getElementById('ref-search').value=ref;
      dd.style.display='none'; doSearch(ref);
    }};
    dd.appendChild(div);
  }});
  dd.style.display='block';
}}

document.getElementById('ref-search-btn').onclick = function(){{ doSearch(document.getElementById('ref-search').value); }};
document.getElementById('ref-search').onkeyup = function(e){{
  if (e.key==='Enter'){{ doSearch(this.value); document.getElementById('ref-search-dropdown').style.display='none'; }}
  else showDropdown(this.value);
}};
document.addEventListener('click', function(e){{
  if (!document.getElementById('ref-search').contains(e.target) && !document.getElementById('ref-search-dropdown').contains(e.target))
    document.getElementById('ref-search-dropdown').style.display='none';
}});

// === postMessage API (for embedding in website) ===
window.addEventListener('message', function(ev) {{
  if (!ev.data || ev.data.type !== 'setYearRange') return;
  var s = parseInt(ev.data.start), e = parseInt(ev.data.end);
  if (isNaN(s) || isNaN(e) || s < 2020 || e > 2025 || s > e) return;
  selStart.value = String(s);
  selEnd.value = String(e);
  rebuildYearLayers();
}});

// If embedded in iframe, hide the in-map year filter (page controls it)
if (window !== window.top) {{
  var yf = document.querySelector('.panel-section:nth-child(2)');
  if (yf) yf.style.display = 'none';
}}

window.setYearRange = function(s, e) {{
  if (isNaN(s) || isNaN(e) || s < 2020 || e > 2025 || s > e) return;
  selStart.value = String(s);
  selEnd.value = String(e);
  rebuildYearLayers();
}};

function notifyParentYear() {{
  if (window.parent && window.parent !== window) {{
    window.parent.postMessage({{
      type: 'mapYearChanged',
      start: yearStart,
      end: yearEnd
    }}, '*');
  }}
}}

}})();
</script>
</body>
</html>'''


def map_consolidated(signal_prox, srts_prox, cb5_crashes, data=None):
    """Consolidated map — print-ready editorial style.

    Base: CartoDB Positron No Labels (clean, minimal, print-friendly).
    Crash data: dot density (one dot per crash) instead of heatmap.
    Layers: denied/approved markers, DOT effectiveness (before-after),
    top-15 spotlight.
    """
    print("  Generating consolidated map (print style)...")
    search_entries = []  # Populated during marker loops for search feature

    # --- Base map: no-label tiles for print clarity ---
    m = folium.Map(
        location=CB5_CENTER, zoom_start=CB5_ZOOM,
        tiles=None,
        control_scale=True,
    )
    folium.TileLayer(
        tiles='https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png',
        attr='&copy; OpenStreetMap contributors &copy; CARTO',
        name='Base Map',
        control=False,
    ).add_to(m)
    folium.TileLayer(
        tiles='https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png',
        attr='&copy; OpenStreetMap contributors &copy; CARTO',
        name='Street Labels',
        overlay=True,
        control=False,
        opacity=0.55,
    ).add_to(m)

    _add_cb5_boundary(m)

    _popup_style = "font-family:'Times New Roman',Georgia,serif;font-size:12px;line-height:1.5;"
    _hr = "<hr style='border:0;border-top:1px solid #ccc;margin:4px 0;'>"

    def _fmt_date(val):
        """Format a date value to 'Mon DD, YYYY' or return 'N/A'."""
        if pd.isna(val):
            return 'N/A'
        try:
            return pd.to_datetime(val).strftime('%b %d, %Y')
        except Exception:
            return str(val)[:10]

    # --- Enrich signal_prox with dates from full CB5 studies data ---
    # The geocode cache may lack daterequested/statusdate (older caches).
    # Merge them from the full studies data so popups and exports have dates.
    if data is not None and 'cb5_no_aps' in data:
        _date_source = data['cb5_no_aps'][['referencenumber', 'daterequested', 'statusdate']].drop_duplicates('referencenumber')
        for col in ['daterequested', 'statusdate']:
            if col not in signal_prox.columns or signal_prox[col].isna().all():
                signal_prox = signal_prox.drop(columns=[col], errors='ignore')
                signal_prox = signal_prox.merge(
                    _date_source[['referencenumber', col]], on='referencenumber', how='left')

    # --- Precompute layer subsets for names and CSV export ---
    _sig_denied = signal_prox[signal_prox['outcome'] == 'denied']
    _sig_approved = signal_prox[signal_prox['outcome'] == 'approved']
    _srts_denied = srts_prox[srts_prox['outcome'] == 'denied']
    _srts_approved = srts_prox[srts_prox['outcome'] == 'approved']
    n_sig_denied = _sig_denied['latitude'].notna().sum()
    n_sig_approved = _sig_approved['latitude'].notna().sum()
    n_srts_denied = _srts_denied['latitude'].notna().sum()
    n_srts_approved = _srts_approved['latitude'].notna().sum()

    # --- Layer 1: Crash Dot Density (replaces heatmap) ---
    crash_with_coords = cb5_crashes[cb5_crashes['latitude'].notna()].copy()
    crash_dots = folium.FeatureGroup(
        name=f'Injury Crashes (n={len(crash_with_coords):,}, 2020–2025)', show=True)
    # Jitter stacked dots so crashes at the same intersection spread apart
    # ~5m offset (0.00005°) — enough to unstick dots, imperceptible geographically
    rng = np.random.RandomState(42)
    jitter_lat = rng.uniform(-0.00005, 0.00005, len(crash_with_coords))
    jitter_lon = rng.uniform(-0.00005, 0.00005, len(crash_with_coords))
    _crash_markers = []  # collect for reuse in clustered layer
    for i, (_, crow) in enumerate(crash_with_coords.iterrows()):
        injured = int(crow.get('number_of_persons_injured', 0))
        killed = int(crow.get('number_of_persons_killed', 0))
        # Size by severity: fatal=4, injury=2, other=1.5
        if killed > 0:
            r, color, opacity = 3.5, '#1a1a1a', 0.8
        elif injured > 0:
            r, color, opacity = 1.8, '#888888', 0.35
        else:
            r, color, opacity = 1.2, '#aaaaaa', 0.2

        # --- Crash popup/tooltip ---
        c_date = _fmt_date(crow.get('crash_date'))
        c_time = str(crow.get('crash_time', '')).strip()
        _on_raw = crow.get('on_street_name')
        _off_raw = crow.get('off_street_name')
        _cross_raw = crow.get('cross_street_name')
        c_on = '' if pd.isna(_on_raw) else str(_on_raw).strip()
        c_off = '' if pd.isna(_off_raw) else str(_off_raw).strip()
        c_cross = '' if pd.isna(_cross_raw) else str(_cross_raw).strip()
        if c_on and c_off:
            c_loc = f"{c_on} & {c_off}"
        elif c_on or c_off:
            c_loc = c_on or c_off
        elif c_cross:
            c_loc = f"Near {c_cross}"
        else:
            c_loc = 'Location on map'
        c_factor = str(crow.get('contributing_factor_vehicle_1', '') or '').strip()
        c_veh1 = str(crow.get('vehicle_type_code1', '') or '').strip()
        ped_inj = int(crow.get('number_of_pedestrians_injured', 0))
        ped_k = int(crow.get('number_of_pedestrians_killed', 0))
        cyc_inj = int(crow.get('number_of_cyclist_injured', 0))
        cyc_k = int(crow.get('number_of_cyclist_killed', 0))
        mot_inj = int(crow.get('number_of_motorist_injured', 0))
        mot_k = int(crow.get('number_of_motorist_killed', 0))

        severity_tag = ('<span style="color:#B44040;font-weight:bold;">FATAL</span>'
                        if killed > 0 else
                        '<span style="color:#cc8400;font-weight:bold;">INJURY</span>'
                        if injured > 0 else 'Property damage')

        crash_popup = (
            f"<div style=\"{_popup_style}\">"
            f"<b>{c_loc}</b><br>"
            f"{c_date} at {c_time}<br>"
            f"Severity: {severity_tag}"
            f"{_hr}"
            f"Pedestrians: {ped_inj} injured, {ped_k} killed<br>"
            f"Cyclists: {cyc_inj} injured, {cyc_k} killed<br>"
            f"Motorists: {mot_inj} injured, {mot_k} killed"
            f"{_hr}"
            f"Factor: {c_factor or 'N/A'}<br>"
            f"Vehicle: {c_veh1 or 'N/A'}<br>"
            f"<span style='color:#666;font-size:10px;'>Collision ID: {crow.get('collision_id', 'N/A')}</span>"
            f"</div>"
        )
        _sev = 'Fatal' if killed > 0 else f'{injured} injured' if injured > 0 else 'Crash'
        crash_tooltip = f"{c_loc} — {_sev}, {c_date}"

        # Store popup/tooltip for reuse in clustered layer
        _crash_markers.append((crow['latitude'], crow['longitude'],
                               color, opacity, crash_popup, crash_tooltip))

        folium.CircleMarker(
            [crow['latitude'] + jitter_lat[i],
             crow['longitude'] + jitter_lon[i]], radius=r,
            color=color, fill=True, fill_color=color,
            fill_opacity=opacity, weight=0.3,
            popup=folium.Popup(crash_popup, max_width=320),
            tooltip=crash_tooltip,
        ).add_to(crash_dots)
    crash_dots.add_to(m)

    # --- Clustered crash layer (off by default, for analysis) ---
    crash_clustered = folium.FeatureGroup(
        name=f'Injury Crashes \u2014 Clustered (n={len(crash_with_coords):,})', show=False)
    _cluster_icon_fn = """
    function(cluster) {
        var count = cluster.getChildCount();
        var size = count < 10 ? 26 : count < 50 ? 32 : 38;
        return L.divIcon({
            html: '<div style="background:rgba(136,136,136,0.8);color:white;' +
                  'font-weight:bold;font-family:Times New Roman,serif;font-size:11px;' +
                  'text-align:center;line-height:' + size + 'px;border-radius:50%;' +
                  'border:1.5px solid #666;">' + count + '</div>',
            className: '',
            iconSize: L.point(size, size)
        });
    }
    """
    crash_cluster = MarkerCluster(
        icon_create_function=_cluster_icon_fn,
        options={
            'maxClusterRadius': 25,
            'spiderfyOnMaxZoom': True,
            'showCoverageOnHover': False,
            'zoomToBoundsOnClick': True,
            'spiderfyDistanceMultiplier': 1.5,
        },
    )
    for lat, lon, color, opacity, popup_html, tooltip_text in _crash_markers:
        d = 6 if color == '#1a1a1a' else 5 if color == '#888888' else 4
        icon_html = (f'<div style="width:{d}px;height:{d}px;background:{color};'
                     f'border-radius:50%;opacity:{opacity};"></div>')
        folium.Marker(
            [lat, lon],
            icon=folium.DivIcon(html=icon_html, icon_size=(d, d),
                                icon_anchor=(d // 2, d // 2)),
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=tooltip_text,
        ).add_to(crash_cluster)
    crash_cluster.add_to(crash_clustered)
    crash_clustered.add_to(m)

    # --- Helper: build signal study popup ---
    def _signal_popup(row, outcome_label, outcome_color):
        ref = row.get('referencenumber', 'N/A')
        req_date = _fmt_date(row.get('daterequested'))
        status_date = _fmt_date(row.get('statusdate'))
        req_type = row.get('requesttype', 'N/A')
        status_desc = str(row.get('statusdescription', '') or '').strip()
        findings = str(row.get('findings', '') or '').strip()
        fatalities = int(row.get('fatalities_150m', 0))
        ped_inj = int(row.get('ped_injuries_150m', 0))
        school = str(row.get('schoolname', '') or '').strip()
        vz = 'Yes' if row.get('visionzero') == 'Yes' else ''
        loc = f"{row.get('mainstreet', '')} & {row.get('crossstreet1', '')}"

        extras = ''
        if school:
            extras += f"School: {school}<br>"
        if vz:
            extras += f"Vision Zero priority: Yes<br>"
        if findings:
            extras += f"Findings: {findings}<br>"

        return (
            f"<div style=\"{_popup_style}\">"
            f"<b>{loc}</b><br>"
            f"<span style='color:#666;font-size:10px;'>{ref}</span><br>"
            f"Type: {req_type}<br>"
            f"Outcome: <span style='color:{outcome_color};font-weight:bold;'>{outcome_label}</span>"
            f"{_hr}"
            f"Requested: {req_date}<br>"
            f"Status date: {status_date}<br>"
            f"Status: {status_desc}"
            f"{_hr}"
            f"{extras}"
            f"<b>Within 150m (2020–2025):</b><br>"
            f"Crashes: {int(row.get('crashes_150m', 0))}<br>"
            f"Injuries: {int(row.get('injuries_150m', 0))}<br>"
            f"Ped. injuries: {ped_inj}<br>"
            f"Fatalities: {fatalities}"
            f"</div>"
        )

    # --- Layer 2: Denied Signal Studies ---
    denied_signals = folium.FeatureGroup(
        name=f'Denied Signal Studies (n={n_sig_denied:,}, 2020–2025)', show=True)
    for _, row in signal_prox[signal_prox['outcome'] == 'denied'].iterrows():
        if pd.isna(row['latitude']):
            continue
        popup_html = _signal_popup(row, 'DENIED', COLORS['denied'])
        folium.CircleMarker(
            [row['latitude'], row['longitude']], radius=6,
            color='#333333', fill=True, fill_color=COLORS['denied'],
            fill_opacity=0.75, weight=1.5,
            popup=folium.Popup(popup_html, max_width=340),
            tooltip=f"{row.get('mainstreet', '')} & {row.get('crossstreet1', '')} — {row.get('requesttype', '')} (DENIED)"
        ).add_to(denied_signals)
        search_entries.append({'ref': row.get('referencenumber', ''), 'lat': row['latitude'],
            'lon': row['longitude'], 'label': f"{row.get('mainstreet', '')} & {row.get('crossstreet1', '')}",
            'type': row.get('requesttype', ''), 'outcome': 'denied'})
    denied_signals.add_to(m)

    # --- Layer 3: Approved Signal Studies ---
    approved_signals = folium.FeatureGroup(
        name=f'Approved Signal Studies (n={n_sig_approved:,}, 2020–2025)', show=True)
    for _, row in signal_prox[signal_prox['outcome'] == 'approved'].iterrows():
        if pd.isna(row['latitude']):
            continue
        popup_html = _signal_popup(row, 'APPROVED', COLORS['approved'])
        folium.CircleMarker(
            [row['latitude'], row['longitude']], radius=6,
            color='#333333', fill=True, fill_color=COLORS['approved'],
            fill_opacity=0.75, weight=1.5,
            popup=folium.Popup(popup_html, max_width=340),
            tooltip=f"{row.get('mainstreet', '')} & {row.get('crossstreet1', '')} — {row.get('requesttype', '')} (APPROVED)"
        ).add_to(approved_signals)
        search_entries.append({'ref': row.get('referencenumber', ''), 'lat': row['latitude'],
            'lon': row['longitude'], 'label': f"{row.get('mainstreet', '')} & {row.get('crossstreet1', '')}",
            'type': row.get('requesttype', ''), 'outcome': 'approved'})
    approved_signals.add_to(m)

    # --- Helper: build SRTS popup ---
    def _srts_popup(row, outcome_label, outcome_color):
        on_st = row.get('onstreet', '')
        from_st = row.get('fromstreet', '')
        to_st = row.get('tostreet', '')
        req_date = _fmt_date(row.get('requestdate'))
        closed_date = _fmt_date(row.get('closeddate'))
        proj_status = str(row.get('projectstatus', '') or '').strip()
        denial = str(row.get('denialreason', '') or '').strip()
        install_date = _fmt_date(row.get('installationdate'))
        proj_code = str(row.get('projectcode', '') or '').strip()
        fatalities = int(row.get('fatalities_150m', 0))
        ped_inj = int(row.get('ped_injuries_150m', 0))
        direction = str(row.get('trafficdirectiondesc', '') or '').strip()

        extras = ''
        if denial:
            extras += f"Denial reason: {denial}<br>"
        if install_date != 'N/A':
            extras += f"Installed: {install_date}<br>"
        if direction:
            extras += f"Traffic: {direction}<br>"

        return (
            f"<div style=\"{_popup_style}\">"
            f"<b>{on_st}</b> ({from_st} to {to_st})<br>"
            f"<span style='color:#666;font-size:10px;'>{proj_code}</span><br>"
            f"Outcome: <span style='color:{outcome_color};font-weight:bold;'>{outcome_label}</span>"
            f"{_hr}"
            f"Requested: {req_date}<br>"
            f"Decision date: {closed_date}<br>"
            f"Project status: {proj_status}"
            f"{_hr}"
            f"{extras}"
            f"<b>Within 150m (2020–2025):</b><br>"
            f"Crashes: {int(row.get('crashes_150m', 0))}<br>"
            f"Injuries: {int(row.get('injuries_150m', 0))}<br>"
            f"Ped. injuries: {ped_inj}<br>"
            f"Fatalities: {fatalities}"
            f"</div>"
        )

    # --- Layer 4: Denied Speed Bumps ---
    denied_srts = folium.FeatureGroup(
        name=f'Denied Speed Bumps (n={n_srts_denied:,}, 2020–2025)', show=True)
    for _, row in srts_prox[srts_prox['outcome'] == 'denied'].iterrows():
        if pd.isna(row['latitude']):
            continue
        popup_html = _srts_popup(row, 'DENIED', COLORS['denied'])
        folium.CircleMarker(
            [row['latitude'], row['longitude']], radius=4,
            color='#333333', fill=True, fill_color=COLORS['denied'],
            fill_opacity=0.6, weight=1,
            popup=folium.Popup(popup_html, max_width=340),
            tooltip=f"{row.get('onstreet', '')} ({row.get('fromstreet', '')} to {row.get('tostreet', '')}) — DENIED"
        ).add_to(denied_srts)
        search_entries.append({'ref': str(row.get('projectcode', '')), 'lat': row['latitude'],
            'lon': row['longitude'], 'label': f"{row.get('onstreet', '')} ({row.get('fromstreet', '')} to {row.get('tostreet', '')})",
            'type': 'Speed Bump', 'outcome': 'denied'})
    denied_srts.add_to(m)

    # --- Layer 5: Approved Speed Bumps ---
    approved_srts = folium.FeatureGroup(
        name=f'Approved Speed Bumps (n={n_srts_approved:,}, 2020–2025)', show=True)
    for _, row in srts_prox[srts_prox['outcome'] == 'approved'].iterrows():
        if pd.isna(row['latitude']):
            continue
        popup_html = _srts_popup(row, 'APPROVED', COLORS['approved'])
        folium.CircleMarker(
            [row['latitude'], row['longitude']], radius=4,
            color='#333333', fill=True, fill_color=COLORS['approved'],
            fill_opacity=0.6, weight=1,
            popup=folium.Popup(popup_html, max_width=340),
            tooltip=f"{row.get('onstreet', '')} ({row.get('fromstreet', '')} to {row.get('tostreet', '')}) — APPROVED"
        ).add_to(approved_srts)
        search_entries.append({'ref': str(row.get('projectcode', '')), 'lat': row['latitude'],
            'lon': row['longitude'], 'label': f"{row.get('onstreet', '')} ({row.get('fromstreet', '')} to {row.get('tostreet', '')})",
            'type': 'Speed Bump', 'outcome': 'approved'})
    approved_srts.add_to(m)

    # --- Layer 6: APS Installed (de3m-c5p4 — court-mandated, separate from merit-based) ---
    _aps_path = f'{DATA_DIR}/aps_installed_citywide.csv'
    if os.path.exists(_aps_path):
        aps_installed = pd.read_csv(_aps_path)
        aps_installed['point_x'] = pd.to_numeric(aps_installed['point_x'], errors='coerce')
        aps_installed['point_y'] = pd.to_numeric(aps_installed['point_y'], errors='coerce')
        aps_installed['date_insta'] = pd.to_datetime(aps_installed['date_insta'], errors='coerce')
        aps_installed['year'] = aps_installed['date_insta'].dt.year

        # Filter: borocd=405 + polygon + 2020–2025
        cb5_aps = aps_installed[aps_installed['borocd'].astype(str).str.strip() == '405'].copy()
        cb5_aps = cb5_aps[cb5_aps['year'].between(2020, 2025)]
        has_coords = cb5_aps['point_x'].notna() & cb5_aps['point_y'].notna()
        cb5_aps = cb5_aps[has_coords]
        _aps_poly = prep(_load_cb5_polygon())
        inside = cb5_aps.apply(
            lambda r: _aps_poly.contains(Point(r['point_x'], r['point_y'])), axis=1)
        cb5_aps = cb5_aps[inside]

        n_aps = len(cb5_aps)
        aps_fg = folium.FeatureGroup(
            name=f'APS Installed (n={n_aps:,}, 2020–2025)', show=False)

        APS_COLOR = '#7B68AE'  # muted purple — distinct from denied/approved/crash
        for _, row in cb5_aps.iterrows():
            inst_date = _fmt_date(row.get('date_insta'))
            location = str(row.get('location', '') or '').strip()
            nta = str(row.get('ntaname', '') or '').strip()
            popup_html = (
                f"<div style=\"{_popup_style}\">"
                f"<b>{location}</b><br>"
                f"<span style='color:{APS_COLOR};font-weight:bold;'>APS INSTALLED</span>"
                f"{_hr}"
                f"Installed: {inst_date}<br>"
                f"Neighborhood: {nta}"
                f"{_hr}"
                f"<span style='color:#666;font-size:10px;'>"
                f"Source: APS Installed Locations [de3m-c5p4]<br>"
                f"Court-mandated (federal ADA lawsuit).<br>"
                f"Excluded from merit-based approval rate analysis.</span>"
                f"</div>"
            )
            folium.CircleMarker(
                [row['point_y'], row['point_x']], radius=5,
                color='#333333', fill=True, fill_color=APS_COLOR,
                fill_opacity=0.75, weight=1,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{location} — APS Installed {inst_date}"
            ).add_to(aps_fg)
            search_entries.append({
                'ref': '', 'lat': row['point_y'], 'lon': row['point_x'],
                'label': location, 'type': 'APS', 'outcome': 'installed'})
        aps_fg.add_to(m)
        print(f"    APS Installed layer: {n_aps} locations")
    else:
        print("    WARNING: APS installed data not found — run scripts_fetch_data.py")
        n_aps = 0

    # --- Layer 7: DOT Effectiveness — before-after for installed locations ---
    # (was Layer 6 before APS layer was added)
    before_after_df = None
    if data is not None:
        before_after_df = _compute_before_after(data)
        effectiveness_fg = folium.FeatureGroup(
            name=f'DOT Effectiveness (n={len(before_after_df)}, Installed, 2020–2025)', show=False)

        for _, ba in before_after_df.iterrows():
            change = ba['crash_change']
            pct = ba['pct_change']

            # Color by outcome: green = decreased, gray = no change, amber = increased
            if change < 0:
                fill_color = '#2d7d46'  # strong green — crashes went down
                outline = '#1a5c2e'
                label = f"{abs(int(pct))}% fewer crashes"
            elif change == 0:
                fill_color = '#777777'  # neutral gray
                outline = '#555555'
                label = "No change"
            else:
                fill_color = '#cc8400'  # amber — crashes went up
                outline = '#996300'
                label = f"{int(pct)}% more crashes"

            install_str = ba['install_date'].strftime('%b %d, %Y')
            ref = ba.get('referencenumber', 'N/A')
            req_date = _fmt_date(ba.get('daterequested'))
            inj_change = ba['after_injuries'] - ba['before_injuries']
            inj_pct = (inj_change / ba['before_injuries'] * 100) if ba['before_injuries'] > 0 else 0
            inj_label = (f"{abs(int(inj_pct))}% fewer" if inj_change < 0
                         else f"{int(inj_pct)}% more" if inj_change > 0
                         else "No change")
            popup_html = (
                f"<div style=\"{_popup_style}\">"
                f"<b>{ba['mainstreet']} & {ba['crossstreet1']}</b><br>"
                f"<span style='color:#666;font-size:10px;'>{ref}</span><br>"
                f"Type: {ba['requesttype']}<br>"
                f"Requested: {req_date}<br>"
                f"Installed: {install_str}"
                f"{_hr}"
                f"<b>Before-After Analysis</b> ({ba['window_months']:.0f}-mo. windows, 150m):<br>"
                f"Crashes: {ba['before_crashes']} &rarr; {ba['after_crashes']} "
                f"(<b style='color:{fill_color};'>{label}</b>)<br>"
                f"Injuries: {ba['before_injuries']} &rarr; {ba['after_injuries']} ({inj_label})"
                f"</div>"
            )

            # Marker size scaled by absolute crash volume (bigger = more data = more reliable)
            marker_r = max(7, min(14, 5 + ba['before_crashes']))

            # 150m radius circle (dashed outline, non-interactive)
            folium.Circle(
                [ba['latitude'], ba['longitude']],
                radius=PROXIMITY_RADIUS_M,
                color=fill_color, fill=True, fill_color=fill_color,
                fill_opacity=0.08, weight=1.5, dash_array='5 3',
                interactive=False,
            ).add_to(effectiveness_fg)
            folium.CircleMarker(
                [ba['latitude'], ba['longitude']], radius=marker_r,
                color=outline, fill=True, fill_color=fill_color,
                fill_opacity=0.8, weight=2,
                popup=folium.Popup(popup_html, max_width=320),
                tooltip=f"{ba['mainstreet']} & {ba['crossstreet1']} — {label}"
            ).add_to(effectiveness_fg)

        effectiveness_fg.add_to(m)

    # --- Layer 7: Top 15 Denied Signal Study Spotlight (default OFF) ---
    # Signal studies only — intersection-level precision. SRTS excluded due to
    # segment-based coordinates creating methodological issues with 150m overlap.
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
    # De-duplicate: name-based then spatial
    spotlight_data = spotlight_data.sort_values('crashes_150m', ascending=False).drop_duplicates(
        subset=['location_name'], keep='first')
    spotlight_data = _spatial_dedup(spotlight_data, radius_m=150)
    top15 = spotlight_data.nlargest(15, 'crashes_150m')

    spotlight_fg = folium.FeatureGroup(name='Top 15 Denied Spotlight (2020–2025)', show=False)
    for rank, (_, row) in enumerate(top15.iterrows(), 1):
        # 150m radius circle
        folium.Circle(
            [row['latitude'], row['longitude']],
            radius=PROXIMITY_RADIUS_M,
            color=COLORS['denied'], fill=True, fill_color=COLORS['denied'],
            fill_opacity=0.08, weight=1.5, dash_array='5 3',
            interactive=False,
        ).add_to(spotlight_fg)

        popup_html = (
            f"<div style=\"{_popup_style}\">"
            f"<b>#{rank}: {row['location_name']}</b><br>"
            f"Dataset: {row['dataset']}<br>"
            f"Request: {row['request_info']}"
            f"{_hr}"
            f"<b>Within 150m:</b><br>"
            f"Crashes: {int(row['crashes_150m'])}<br>"
            f"Injuries: {int(row['injuries_150m'])}<br>"
            f"Ped. injuries: {int(row['ped_injuries_150m'])}<br>"
            f"Fatalities: {int(row['fatalities_150m'])}"
            f"</div>"
        )
        folium.CircleMarker(
            [row['latitude'], row['longitude']], radius=9,
            color='#333333', fill=True, fill_color=COLORS['denied'],
            fill_opacity=0.85, weight=2,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"#{rank}: {row['location_name']} ({int(row['crashes_150m'])} crashes)"
        ).add_to(spotlight_fg)

        # Rank label (non-interactive so it doesn't block clicks on markers below)
        folium.Marker(
            [row['latitude'], row['longitude']],
            icon=folium.DivIcon(
                html=(f"<div style=\"font-family:'Times New Roman',Georgia,serif;"
                      f"font-size:10px;font-weight:bold;color:white;"
                      f"text-align:center;margin-top:-5px;"
                      f"pointer-events:none;\">{rank}</div>"),
                icon_size=(20, 20), icon_anchor=(10, 10)),
            interactive=False,
        ).add_to(spotlight_fg)

    spotlight_fg.add_to(m)

    # --- Layer 8: Top 10 Crash Intersections (default OFF) ---
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

    crash_top_fg = folium.FeatureGroup(
        name=f'Top 10 Crash Intersections (2020\u20132025)', show=False)
    for rank, (_, cr) in enumerate(top10_crashes.iterrows(), 1):
        popup_html = (
            f"<div style=\"{_popup_style}\">"
            f"<b>#{rank}: {cr['intersection']}</b>"
            f"{_hr}"
            f"<b>Crashes:</b> {int(cr['crashes'])}<br>"
            f"<b>Total injuries:</b> {int(cr['injuries'])}<br>"
            f"Pedestrian: {int(cr['ped_injuries'])}<br>"
            f"Cyclist: {int(cr['cyc_injuries'])}<br>"
            f"<b>Fatalities:</b> {int(cr['fatalities'])}"
            f"</div>"
        )
        # 150m radius circle (dashed outline, non-interactive)
        folium.Circle(
            [cr['lat'], cr['lon']],
            radius=PROXIMITY_RADIUS_M,
            color=COLORS['primary'], fill=True, fill_color=COLORS['primary'],
            fill_opacity=0.08, weight=1.5, dash_array='5 3',
            interactive=False,
        ).add_to(crash_top_fg)
        # Center dot
        folium.CircleMarker(
            [cr['lat'], cr['lon']], radius=9,
            color='#333333', fill=True, fill_color=COLORS['primary'],
            fill_opacity=0.85, weight=2,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"#{rank}: {cr['intersection']} ({int(cr['crashes'])} crashes)"
        ).add_to(crash_top_fg)
        # Rank label (non-interactive)
        folium.Marker(
            [cr['lat'], cr['lon']],
            icon=folium.DivIcon(
                html=(f"<div style=\"font-family:'Times New Roman',Georgia,serif;"
                      f"font-size:10px;font-weight:bold;color:white;"
                      f"text-align:center;margin-top:-5px;"
                      f"pointer-events:none;\">{rank}</div>"),
                icon_size=(20, 20), icon_anchor=(10, 10)),
            interactive=False,
        ).add_to(crash_top_fg)
    crash_top_fg.add_to(m)

    # --- Legend (print-ready, no heatmap entry) ---
    legend_items = [
        (COLORS['denied'], 'Denied request', 'Denied Signal,Denied Speed'),
        (COLORS['approved'], 'Approved request', 'Approved Signal,Approved Speed'),
        ('#7B68AE', 'APS installed', 'APS Installed'),
        ('#888888', 'Injury crash (dot = 1 crash)', 'Injury Crashes'),
        ('#1a1a1a', 'Fatal crash', 'Injury Crashes'),
        (COLORS['primary'], 'Top 10 crash intersection', 'Top 10 Crash', 'spotlight'),
        (COLORS['denied'], 'Top 15 denied spotlight', 'Top 15 Denied', 'spotlight'),
    ]
    if before_after_df is not None:
        legend_items.extend([
            ('#2d7d46', 'Installed \u2014 crashes decreased', 'DOT Effectiveness', 'spotlight'),
            ('#cc8400', 'Installed \u2014 crashes increased', 'DOT Effectiveness', 'spotlight'),
        ])
    legend_html = _make_legend_html(legend_items)
    m.get_root().html.add_child(folium.Element(legend_html))

    # --- CSS + dynamic title + search ---
    _inject_map_css(m)
    _add_dynamic_title(m)
    _add_search_box(m, search_entries)

    # --- Layer control ---
    folium.LayerControl(collapsed=False).add_to(m)

    m.save(f'{OUTPUT_DIR}/map_01_crash_denial_overlay.html')
    print("    Consolidated map saved to map_01_crash_denial_overlay.html")

    # --- Export layer data as CSV spreadsheets ---
    print("    Exporting map layer spreadsheets...")

    # Layer 1: Crashes
    crash_cols = ['crash_date', 'crash_time', 'on_street_name', 'off_street_name',
                  'number_of_persons_injured', 'number_of_persons_killed',
                  'number_of_pedestrians_injured', 'number_of_pedestrians_killed',
                  'number_of_cyclist_injured', 'number_of_cyclist_killed',
                  'number_of_motorist_injured', 'number_of_motorist_killed',
                  'contributing_factor_vehicle_1', 'vehicle_type_code1',
                  'collision_id', 'latitude', 'longitude']
    _crash_export = crash_with_coords[[c for c in crash_cols if c in crash_with_coords.columns]].copy()
    _crash_export['Source Dataset'] = 'Motor Vehicle Collisions [h9gi-nx95]'
    _crash_export.to_csv(f'{OUTPUT_DIR}/map_layer_crashes.csv', index=False)

    # Layer 2-3: Signal Studies (denied + approved)
    # Enrich with fields from original data not carried through geocode cache
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
        _exp = _exp[[c for c in sig_cols if c in _exp.columns]]
        _exp['Source File'] = 'data_cb5_signal_studies.csv'
        _exp.to_csv(f'{OUTPUT_DIR}/map_layer_{outcome_label}_signals.csv', index=False)

    # Layer 4-5: Speed Bumps (denied + approved)
    srts_cols = ['projectcode', 'onstreet', 'fromstreet', 'tostreet',
                 'outcome', 'requestdate', 'closeddate', 'projectstatus', 'denialreason',
                 'installationdate', 'trafficdirectiondesc',
                 'crashes_150m', 'injuries_150m', 'ped_injuries_150m', 'fatalities_150m',
                 'latitude', 'longitude']
    for outcome_label, subset in [('denied', _srts_denied), ('approved', _srts_approved)]:
        _exp = subset[[c for c in srts_cols if c in subset.columns]].copy()
        _exp = _exp[_exp['latitude'].notna()]
        _exp['Source File'] = 'srts_citywide.csv'
        _exp.to_csv(f'{OUTPUT_DIR}/map_layer_{outcome_label}_speed_bumps.csv', index=False)

    # Layer 6: APS Installed
    if n_aps > 0:
        aps_cols = ['location', 'date_insta', 'ntaname', 'point_x', 'point_y']
        _aps_export = cb5_aps[[c for c in aps_cols if c in cb5_aps.columns]].copy()
        _aps_export = _aps_export.rename(columns={'point_y': 'latitude', 'point_x': 'longitude'})
        _aps_export['Source Dataset'] = 'APS Installed Locations [de3m-c5p4]'
        _aps_export.to_csv(f'{OUTPUT_DIR}/map_layer_aps_installed.csv', index=False)

    # Top 15 Spotlight
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

    # --- Export JSON for interactive map ---
    _export_map_json(signal_prox, srts_prox, cb5_crashes, data, before_after_df,
                     search_entries, top15, top10_crashes,
                     cb5_aps=cb5_aps if n_aps > 0 else None)

    return before_after_df, search_entries, top15, top10_crashes, (cb5_aps if n_aps > 0 else None)


# ============================================================
# Step 4: Static Charts (Matplotlib)
# ============================================================

def _draw_proximity_panel(df, title_prefix, filename, chart_label):
    """Draw a single-panel crash proximity chart (denied vs approved)."""
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
    ax.set_title(f'Crash Proximity: Denied vs. Approved {title_prefix}\n(n={len(denied)+len(approved):,}, Median Crash Metrics, 2020–2025)',
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
             'Crash data: Queens injury crashes [2020–2025], Motor Vehicle Collisions [h9gi-nx95]',
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
    """Normalize intersection name by sorting streets alphabetically.

    Ensures 'Cooper Ave & Cypress Ave' == 'Cypress Ave & Cooper Ave'.
    """
    a = str(street_a).strip().title() if pd.notna(street_a) else ''
    b = str(street_b).strip().title() if pd.notna(street_b) else ''
    parts = sorted([a, b])
    return f'{parts[0]} & {parts[1]}'


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
    ax.set_title(f'Top 15 Denied Signal Study Intersections by Nearby Crash Count\n(150m Radius, n={n_unique:,} unique denied intersections, 2020–2025)',
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
    ax.set_title(f'Top 15 Denied Signal Study Intersections by Nearby Injuries\n(150m Radius, n={n_unique:,} unique denied intersections, 2020–2025)',
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

    # Full CB5 pipeline: cb=405 + cross-street exclusion + polygon filter
    cb5 = _load_cb5_srts_full()
    cb5['requestdate'] = pd.to_datetime(cb5['requestdate'], errors='coerce')
    feasible = cb5[cb5['segmentstatusdescription'] == 'Feasible'].copy()

    min_yr = int(feasible['requestdate'].dt.year.min())
    max_yr = min(int(feasible['requestdate'].dt.year.max()), 2025)

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
    axes[0].bar(['Approved\nby DOT'], [n_total], color=COLORS['approved'],
                edgecolor='black', zorder=3, width=0.5)
    axes[0].text(0, n_total + 5, str(n_total), ha='center', va='bottom',
                 fontweight='bold', fontsize=14)
    axes[0].set_ylabel('Number of Requests', fontweight='bold')
    axes[0].set_title(f'Total Approved\n({min_yr}–{max_yr})', fontweight='bold', fontsize=12)
    axes[0].set_ylim(0, n_total * 1.15)
    axes[0].xaxis.grid(False)

    # Right panel: what happened to them (only include Closed if any exist)
    categories = ['Confirmed\nInstalled', 'Cancelled /\nRejected']
    values = [n_installed, n_cancelled]
    bar_colors = ['#2d7d46', '#cc8400']
    if n_closed > 0:
        categories.append('Closed\n(No Install)')
        values.append(n_closed)
        bar_colors.append('#b0b0b0')
    categories.append('Still\nWaiting')
    values.append(n_waiting)
    bar_colors.append('#888888')

    bars = axes[1].bar(categories, values, color=bar_colors, edgecolor='black', zorder=3, width=0.6)

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

    # Median wait annotation — position on the "Still Waiting" bar (last bar)
    still_open_dt = pd.to_datetime(still_open['requestdate'], errors='coerce')
    waiting_bar_idx = len(categories) - 1
    if len(still_open_dt.dropna()) > 0:
        median_years = (pd.Timestamp.now() - still_open_dt).dt.days.median() / 365.25
        axes[1].annotate(f'Median wait: {median_years:.1f} years',
                         xy=(waiting_bar_idx, n_waiting * 0.5), ha='center', fontsize=9,
                         style='italic', fontweight='bold',
                         bbox=dict(boxstyle='round', facecolor='lightyellow',
                                   edgecolor='gray', alpha=0.9))

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

    # Table 09b: Aggregate comparison — denied vs approved
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
    version = DATA_BUNDLE_VERSION
    bundle_path = os.path.join(OUTPUT_DIR, f'data_bundle_v{version}.zip')
    patterns = ['chart_*.png', 'table_*.csv', 'map_01_*.html',
                'map_layer_*.csv', 'METHODOLOGY.md']
    with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for pattern in patterns:
            for f in sorted(_glob.glob(os.path.join(OUTPUT_DIR, pattern))):
                zf.write(f, os.path.basename(f))
    n_files = sum(1 for _ in zipfile.ZipFile(bundle_path).namelist())
    print(f"  Data bundle saved: {bundle_path} ({n_files} files)")


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

    # Step 3: Consolidated map (replaces former Maps 01-03)
    print("\nStep 3: Generating consolidated map...")
    before_after_df, search_entries, top15, top10_crashes, cb5_aps = map_consolidated(
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
