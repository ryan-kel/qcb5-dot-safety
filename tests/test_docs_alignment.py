import csv
import re
import unittest
from collections import Counter
from pathlib import Path


SHARED_DATAVIZ_GUIDE = (
    Path.home() / 'sites' / 'electoralanalytics-site' / 'docs' / 'style' / 'dataviz.md'
)


class DocumentationAlignmentTest(unittest.TestCase):
    def read(self, path):
        return Path(path).read_text(encoding='utf-8')

    def csv_rows(self, path):
        with Path(path).open(newline='', encoding='utf-8') as handle:
            return list(csv.DictReader(handle))

    def classify_signal_status(self, status):
        status = (status or '').lower()
        if 'denial' in status or ('engineering study completed' in status and 'approval' not in status):
            return 'denied'
        approved_terms = ['approval', 'approved', 'aps installed', 'aps ranking', 'aps design']
        if any(term in status for term in approved_terms):
            return 'approved'
        return 'pending'

    def test_readme_documents_canonical_run_path_and_curated_input(self):
        text = self.read('README.md')
        self.assertIn('Reproduce Current Committed Outputs', text)
        self.assertIn('Live Data Refresh', text)
        self.assertIn('python scripts_fetch_data.py', text)
        self.assertIn('python generate_charts.py', text)
        self.assertIn('python generate_maps.py', text)
        self.assertIn('python scripts_validate_outputs.py', text)
        self.assertIn('uses the committed `data_raw/` snapshot', text)
        self.assertIn('pins the current committed snapshot', text)
        self.assertIn('output/data_cb5_signal_studies.csv` is a curated input', text)
        self.assertIn('data_cb5_signal_studies_provenance.csv', text)
        self.assertIn('495 matched rows, 3 duplicate raw matches', text)
        self.assertIn('CQ25-0457B', text)
        self.assertIn('data_unmatched_signal_geocodes.csv', text)
        self.assertIn('output/source_manifest.json', text)
        self.assertIn('build timestamp, analysis window', text)
        self.assertIn('data_raw/fetch_manifest.json', text)
        self.assertIn('per-dataset fetch timestamps', text)
        self.assertIn('stable Socrata `$order` fields', text)
        self.assertIn('planned Socrata query parameters', text)
        self.assertIn('input schemas', text)
        self.assertIn('map point geometry', text)
        self.assertIn('proximity/map-layer joins', text)
        self.assertIn('chart and table artifacts', text)
        self.assertIn('calculated rates and percentages', text)
        self.assertIn('source labels', text)
        self.assertIn('remaining publication blockers', text)
        self.assertNotIn('still requires a full refresh', text)

    def test_readme_documents_curated_signal_input_and_refresh_guardrails(self):
        text = self.read('README.md')
        self.assertNotIn('analysis_notebook.ipynb', text)
        self.assertIn('curated input', text)
        self.assertIn('source_manifest.json', text)
        self.assertIn('fetch_manifest.json', text)
        self.assertIn('Live Data Refresh', text)
        self.assertIn('review `data_raw/fetch_manifest.json`', text)
        self.assertIn('495 matched rows', text)
        self.assertNotIn('court-mandated', text)
        self.assertNotIn('federal lawsuit', text)
        self.assertIn('date.today().year - 1', self.read('generate_maps.py'))

    def test_style_guide_matches_last_complete_year_window(self):
        text = SHARED_DATAVIZ_GUIDE.read_text(encoding='utf-8')
        self.assertIn('last complete calendar year', text)
        self.assertIn('date.today().year - 1', text)
        self.assertNotIn('hard-capped at the current year', text)
        self.assertNotIn('CURRENT_YEAR', text)

    def test_public_copy_uses_style_guide_comparison_language(self):
        public_docs = [
            'output/METHODOLOGY.md',
            'REFERENCE_data_dictionary.md',
        ]
        for path in public_docs:
            text = self.read(path)
            self.assertNotRegex(text, r'\b[vV]s\.?\b|versus', path)

        chart_code = self.read('generate_charts.py')
        map_code = self.read('generate_maps.py')
        self.assertIn('QCB5 and Citywide Signal Study Denial Rates by Year', chart_code)
        self.assertIn('QCB5 and Citywide Speed Bump Denial Rates by Year', chart_code)
        self.assertIn('DOT Denial Rates by Request Type: QCB5 and Citywide', chart_code)
        self.assertIn('Signal Studies and Speed Bumps with Injury and Fatal Crashes', map_code)
        self.assertIn('Crash Proximity: Denied and Approved', map_code)
        for stale_phrase in [
            'QCB5 Signal Study Denial Rates by Year, vs. Citywide',
            'QCB5 Speed Bump Denial Rates by Year, vs. Citywide',
            'QCB5 vs. Citywide',
            'Signal Studies & Speed Bumps vs.',
            'Requests vs.',
            'Denied vs. Approved',
        ]:
            self.assertNotIn(stale_phrase, chart_code)
            self.assertNotIn(stale_phrase, map_code)

    def test_source_docs_match_current_fetch_logic(self):
        text = self.read('REFERENCE_data_sources.md')
        self.assertIn('311 Service Requests from 2020 to Present', text)
        self.assertNotIn('311-Service-Requests-from-2010-to-Present', text)
        self.assertIn('Speed-Reducer-Tracking-System-SRTS-/9n6h-pt9g', text)
        self.assertNotIn('Speed-Reducer-Tracking-System/9n6h-pt9g', text)
        self.assertIn('bounding-box candidates', text)
        self.assertIn('does not require `borough=', text)
        self.assertIn('checks the curated rows against the committed raw snapshot', text)
        self.assertNotIn("Filtered for `borough`='QUEENS'", text)

    def test_boundary_docs_use_current_srts_polygon_counts(self):
        text = self.read('REFERENCE_cb5_boundaries.md')
        self.assertIn('| 1 | Resolved raw records (`cb=405`) | 2,170 |', text)
        self.assertIn('| 2 | After polygon boundary filter | 2,142 |', text)
        self.assertIn('| — | Excluded by polygon filter | 28 |', text)
        self.assertIn('| Feature id | `405` |', text)
        self.assertIn('| Coordinate points | `51` |', text)
        self.assertIn('| Bounds | lon -73.924519 to -73.855294; lat 40.682342 to 40.735120 |', text)
        self.assertNotIn('Wikipedia', text)

    def test_methodology_uses_exact_srts_boundary_counts_and_existing_references(self):
        text = self.read('output/METHODOLOGY.md')
        self.assertIn('28 resolved records excluded', text)
        self.assertIn('2,170 resolved `cb=405` SRTS records -> 2,142 retained', text)
        self.assertNotIn('~26', text)
        self.assertNotIn('decisions.md', text)

    def test_data_dictionary_signal_request_type_counts_match_raw_snapshot(self):
        text = self.read('REFERENCE_data_dictionary.md')
        rows = self.csv_rows('data_raw/signal_studies_citywide.csv')
        request_types = [
            'Traffic Signal',
            'All-Way Stop',
            'Accessible Pedestrian Signal',
            'Left Turn Arrow/Signal',
            'Leading Pedestrian Interval',
        ]
        for request_type in request_types:
            matching = [row for row in rows if row['requesttype'] == request_type]
            resolved = [
                row for row in matching
                if self.classify_signal_status(row['statusdescription']) in {'denied', 'approved'}
            ]
            denied = [
                row for row in resolved
                if self.classify_signal_status(row['statusdescription']) == 'denied'
            ]
            denial_rate = round(len(denied) / len(resolved) * 100, 1)
            self.assertIn(f'| {request_type} |', text)
            self.assertIn(f'| {request_type} ', text)
            self.assertIn(f'| {len(matching):,} | {denial_rate:.1f}%', text)

    def test_data_dictionary_aps_counts_match_raw_snapshot(self):
        text = self.read('REFERENCE_data_dictionary.md')
        rows = self.csv_rows('data_raw/aps_installed_citywide.csv')
        borough_counts = Counter(row['borough'] for row in rows)
        cb5_count = sum(1 for row in rows if row['borocd'].strip() == '405')

        self.assertIn(f'**Records in current committed raw snapshot**: {len(rows):,} installed citywide', text)
        for borough in ['Brooklyn', 'Queens', 'Bronx', 'Manhattan', 'Staten Island']:
            self.assertIn(f'| {borough} | {borough_counts[borough]:,} |', text)
        self.assertIn(f'| **CB5 Queens (`borocd=405`)** | **{cb5_count:,}** |', text)

    def test_data_dictionary_srts_denial_reasons_match_generated_table(self):
        text = self.read('REFERENCE_data_dictionary.md')
        for row in self.csv_rows('output/table_05b_cb5_denial_reasons.csv'):
            self.assertIn(f"| {row['Reason']} | {int(row['Count']):,} |", text)
        self.assertNotIn('34,245', text)

    def test_methodology_has_freshness_warning_and_current_key_counts(self):
        text = self.read('output/METHODOLOGY.md')
        self.assertIn('Publication readiness note', text)
        self.assertIn('duplicate `CQ21-0749` rows', text)
        self.assertIn('10 unmatched signal-study geocodes', text)
        self.assertNotIn('partially corrected after audit', text)
        self.assertNotIn('full regeneration pass before publication', text)
        self.assertIn('| Signal Studies | `[w76s-c5u4]` | `data_raw/signal_studies_citywide.csv` | 76,748 |', text)
        self.assertIn('| CB5 Signal Studies | Derived | `output/data_cb5_signal_studies.csv` | 499 |', text)
        self.assertIn('pre-filtered curated file (`output/data_cb5_signal_studies.csv`)', text)
        self.assertIn('98% geocoded (422/432 current resolved non-APS rows)', text)
        self.assertIn('data_unmatched_signal_geocodes.csv', text)
        self.assertIn('495 rows match once', text)
        self.assertIn('1 curated row (`CQ25-0457B`) is not present', text)
        self.assertIn('does not by itself validate CB5 inclusion', text)
        self.assertIn('do not appear in the signal-study map layers or proximity statistics', text)
        self.assertIn('injury or fatal crashes', text)
        self.assertIn('measured 85th-percentile radar travel speed below 30 mph', text)
        self.assertNotIn('Batting Average Analysis', text)
        self.assertNotIn('The infrastructure works', text)
        self.assertNotIn('Data fetched: 2026-02-11', text)
        self.assertNotIn('hard-capped at 2025', text)
        self.assertNotIn('contains only injury crashes', text)

    def test_methodology_references_current_generated_chart_artifacts(self):
        text = self.read('output/METHODOLOGY.md')
        for current_name in [
            'chart_03a_signal_volume.png',
            'chart_03b_signal_denial_rates.png',
            'chart_03c_srts_volume.png',
            'chart_03d_srts_denial_rates.png',
            'chart_05a_queens_cb_denial_rates.png',
            'chart_05b_denial_reasons.png',
            'chart_05c_denial_reasons_by_year.png',
            'chart_08a_crash_count.png',
            'chart_08b_crash_injuries.png',
        ]:
            self.assertIn(current_name, text)
        for stale_name in [
            'chart_03_year_over_year_print.png',
            'chart_03_year_over_year_print_hires.png',
            'chart_03_year_over_year_trends.png',
            'chart_05_speed_bump_analysis.png',
            'chart_05_speed_bump_analysis_print.png',
            'chart_08_crash_hotspots_cb5.png',
        ]:
            self.assertNotIn(stale_name, text)

    def test_public_docs_reference_existing_or_explicitly_optional_files(self):
        docs = [
            'README.md',
            'REFERENCE_data_dictionary.md',
            'REFERENCE_data_sources.md',
            'REFERENCE_cb5_boundaries.md',
            'output/METHODOLOGY.md',
        ]
        allowed_optional = {
            'data_raw/fetch_manifest.json',
            '~/sites/electoralanalytics-site/docs/style/dataviz.md',
        }
        reference_pattern = re.compile(
            r'`([^`\s]+\.(?:csv|png|html|json|md|zip|geojson))`'
            r'|\(([^)\s]+\.(?:csv|png|html|json|md|zip|geojson))\)'
        )

        missing = []
        for doc in docs:
            base = Path(doc).parent
            text = self.read(doc)
            refs = sorted({match[0] or match[1] for match in reference_pattern.findall(text)})
            for ref in refs:
                if ref.startswith(('http://', 'https://')) or ref in allowed_optional:
                    continue
                candidates = [Path(ref)]
                if doc.startswith('output/') and not ref.startswith(('output/', 'data_raw/')):
                    candidates.append(base / ref)
                if not any(candidate.exists() for candidate in candidates):
                    missing.append((doc, ref))

        self.assertEqual(missing, [])

    def test_data_dictionary_does_not_claim_raw_signal_reference_numbers_are_unique(self):
        text = self.read('REFERENCE_data_dictionary.md')
        self.assertIn('not guaranteed unique in the committed raw snapshot', text)
        self.assertIn('output/table_01d_denied_vs_approved.csv', text)
        self.assertNotIn('| `referencenumber` | Unique request ID |', text)

    def test_methodology_uses_statistically_precise_language(self):
        text = self.read('output/METHODOLOGY.md')
        aggregate = self.csv_rows('output/table_09b_aggregate_comparison.csv')
        signal = next(row for row in aggregate if row['Dataset'] == 'Signal Studies')
        srts = next(row for row in aggregate if row['Dataset'] == 'SRTS')

        self.assertIn('Within the geocoded signal-study subset', text)
        self.assertIn(f"Mann-Whitney p={signal['Mann-Whitney p-value (crashes)']}", text)
        self.assertIn(f"p={srts['Mann-Whitney p-value (crashes)']}", text)
        self.assertIn('tied-rank variance correction', text)
        self.assertIn('not by itself prove causation or show DOT intent', text)
        self.assertIn('p-values are not the probability', text)
        self.assertNotIn('probability this pattern is due to chance', text)
        self.assertNotIn('systematically denying requests at more dangerous locations', text)
        self.assertNotIn('confirming that speed bump denials are driven', text)
        self.assertNotIn('using radar speed as the sole determinant and ignoring crash history entirely', text)

    def test_public_language_avoids_unsupported_legal_and_causal_claims(self):
        public_paths = [
            'output/METHODOLOGY.md',
            'REFERENCE_data_dictionary.md',
            str(SHARED_DATAVIZ_GUIDE),
            'generate_charts.py',
            'generate_maps.py',
            'templates/map_02_template.html',
            'output/map_02_interactive_explorer.html',
        ]
        unsupported_phrases = [
            'court-mandated',
            'Court-mandated',
            'federal lawsuit',
            'American Council of the Blind',
            'mandating installation',
            'unfulfillable',
            'system cannot grant',
            'institutional refusal',
            'DOT said no',
            'near-universal denial',
            'masking the reality',
            'requires no statistical interpretation',
            'ceased to function as a public service',
            'most alarming trend',
            'suggests the infrastructure works',
            'driven almost entirely',
            'unreasonable request patterns',
        ]
        for path in public_paths:
            text = self.read(path)
            for phrase in unsupported_phrases:
                self.assertNotIn(phrase, text, f'{phrase!r} in {path}')

        methodology = self.read('output/METHODOLOGY.md')
        self.assertIn('This is an analytic classification, not a direct DOT status label.', methodology)
        self.assertIn('Installed APS inventory.', self.read('templates/map_02_template.html'))
        self.assertIn('Installed APS inventory.', self.read('output/map_02_interactive_explorer.html'))
        self.assertIn('APS inventory (excl. from denial rates)', self.read('generate_charts.py'))

    def test_methodology_headline_counts_match_current_tables(self):
        text = self.read('output/METHODOLOGY.md')
        rows = self.csv_rows('output/table_01d_denied_vs_approved.csv')
        signal = next(row for row in rows if row['Dataset'] == 'Signal Studies (Excl. APS)')
        speed_bumps = next(row for row in rows if row['Dataset'] == 'Speed Bumps')

        self.assertIn(
            f"{signal['Denied']} denied and {signal['Approved']} approved signal studies excluding APS",
            text,
        )
        self.assertIn(
            f"{speed_bumps['Denied']} denied and {speed_bumps['Approved']} approved speed bump requests",
            text,
        )
        self.assertIn(f"n={speed_bumps['Denied']} denials", text)

    def test_methodology_map_layer_counts_match_current_exports(self):
        text = self.read('output/METHODOLOGY.md')
        layers = [
            ('Injury Crashes', 'ON', 'map_layer_crashes.csv'),
            ('Denied Signal Studies', 'ON', 'map_layer_denied_signals.csv'),
            ('Approved Signal Studies', 'ON', 'map_layer_approved_signals.csv'),
            ('Denied Speed Bumps', 'ON', 'map_layer_denied_speed_bumps.csv'),
            ('Approved Speed Bumps', 'ON', 'map_layer_approved_speed_bumps.csv'),
        ]
        for label, default, csv_name in layers:
            rows = len(self.csv_rows(f'output/{csv_name}'))
            self.assertIn(f'| {label} | {default} | {rows:,} |', text)
            self.assertIn(f'| `{csv_name}` | {rows:,} |', text)

    def test_methodology_srts_funnel_matches_current_table(self):
        text = self.read('output/METHODOLOGY.md')
        rows = {row['Category']: row for row in self.csv_rows('output/table_15_srts_funnel.csv')}
        total = rows['Total Approved (Feasible)']
        installed = rows['Confirmed Installed']
        cancelled = rows['Cancelled / Rejected']
        closed = rows['Closed (No Install)']
        waiting = rows['Still Waiting']

        self.assertIn(f"{total['Count']} QCB5 speed bump approvals", text)
        self.assertIn(f"Confirmed Installed at {installed['Count']} ({installed['Percent']}%)", text)
        self.assertIn(f"Cancelled/Rejected at {cancelled['Count']} ({cancelled['Percent']}%)", text)
        self.assertIn(f"Closed Without Install at {closed['Count']} ({closed['Percent']}%)", text)
        self.assertIn(f"Still Waiting at {waiting['Count']} ({waiting['Percent']}%)", text)
        self.assertIn(f"cancelled after the fact ({cancelled['Count']})", text)
        self.assertIn(f"actually installed ({installed['Count']})", text)
        self.assertNotIn('approximately 237', text)
        self.assertNotIn('~21 locations', text)
        self.assertNotIn('approximately 48% cancellation rate', text)

    def test_srts_pipeline_docs_do_not_reintroduce_cross_street_exclusion(self):
        self.assertNotIn(
            'cb=405 + cross-street exclusion + polygon filter',
            self.read('generate_maps.py'),
        )

    def test_export_map_dependency_is_declared(self):
        export_script = self.read('export_map_png.py')
        requirements = self.read('requirements.txt')
        readme = self.read('README.md')
        self.assertIn('from playwright.sync_api import sync_playwright', export_script)
        self.assertIn('playwright>=', requirements)
        self.assertIn('python -m pip install -r requirements.txt', readme)
        self.assertIn('python -m playwright install chromium', readme)
        self.assertNotIn('npm install', readme)
        self.assertFalse(Path('package.json').exists())
        self.assertFalse(Path('package-lock.json').exists())

    def test_fetch_script_does_not_reference_known_stale_boundary_endpoints(self):
        text = self.read('scripts_fetch_data.py')
        self.assertNotIn('jp9i-3b7y', text)
        self.assertNotIn('yfnk-k7r4', text)
        self.assertNotIn('5crt-au7u', text)
        self.assertNotIn('311-Service-Requests-from-2010-to-Present', text)
        self.assertIn('311-Service-Requests-from-2020-to-Present', text)

    def test_interactive_explorer_security_theme_and_external_data(self):
        import json as _json
        self.assertFalse(Path('output/map_01_crash_denial_overlay.html').exists())
        map_path = Path('output/map_02_interactive_explorer.html')
        self.assertTrue(map_path.exists())
        self.assertLess(map_path.stat().st_size, 100_000)
        html = map_path.read_text(encoding='utf-8')
        self.assertIn("fetch(cacheBust('map_data.json'))", html)
        self.assertNotIn('var DATA = {', html)
        self.assertIn('var yearStart = 2020, yearEnd = 2025;', html)
        self.assertNotIn('body.embedded #year-filter-section', html)
        self.assertNotIn("'*'", html)
        self.assertIn("ev.origin !== window.location.origin", html)
        self.assertIn("sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H", html)
        self.assertIn("sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH", html)
        self.assertIn("sha384-pmjIAcz2bAn0xukfxADbZIb3t8oRT9Sv0rvO+BR5Csr6Dhqq+nZs59P0pPKQJkEV", html)
        self.assertIn("sha384-wgw+aLYNQ7dlhK47ZPK7FRACiq7ROZwgFNg0m04avm4CaXS+Z9Y7nMu8yNjBKYC+", html)
        self.assertIn("sha384-eXVCORTRlv4FUUgS/xmOyr66XBVraen8ATNLMESp92FKXLAMiKkerixTiBvXriZr", html)
        self.assertIn("ea-color-scheme", html)
        self.assertIn("ea-standalone-bar", html)
        self.assertIn("IBM+Plex+Sans", html)
        self.assertIn("dark_all", html)
        self.assertIn("key=cb1_2949_1_9bd5bcde55f90cb1ce920410", html)
        self.assertIn('role="combobox"', html)
        self.assertIn("zoomSnap: 0.25", html)
        self.assertIn("scrollWheelZoom: !isEmbedded", html)
        self.assertIn("prefers-reduced-motion: reduce", html)
        self.assertIn("#7C5B12", html)
        self.assertIn("#C43E2F", html)
        self.assertIn("#1D6F8A", html)
        self.assertIn("makeDiamondIcon", html)
        self.assertNotIn("outline: none", html)
        self.assertLess(html.index('id="panel"'), html.index('id="map"'))
        curated = _json.loads(Path('output/curated_charts.json').read_text(encoding='utf-8'))
        self.assertEqual(6, len(curated['summary_charts']))
        for item in curated['summary_charts']:
            self.assertTrue((Path('output') / item['file']).exists(), item['file'])


if __name__ == '__main__':
    unittest.main()
