# QCB5 DOT Safety: AGENTS.md

**Slug:** `qcb5-dot-safety` · **Layout:** `analysis` · **Docs:** `README.md`

Approval-rate analysis of NYC DOT safety requests in Queens CB5 (signals, speed reducers, crashes).

## Data & Invariants

- **NYC Open Data:** Signal studies `w76s-c5u4`, SRTS `9n6h-pt9g`, crashes `h9gi-nx95`.
- CB5 polygon is the sole geographic authority for coordinate-bearing layers. Reproduce outputs from committed `data_raw/` before changing methodology.

## Pipeline

```bash
.venv/bin/python generate_charts.py && .venv/bin/python generate_maps.py
.venv/bin/python scripts_build_curated_provenance.py
.venv/bin/python scripts_build_manifest.py
.venv/bin/python -m unittest discover -s tests
```

Note: `scripts_validate_outputs.py` is currently saved in `git stash` (`stash@{0}`, untracked-files parent `stash@{0}^3`). Do not pop it expecting a green run: its pinned counts predate the current committed `data_raw/` snapshot (trial run 2026-11-08 failed on raw row counts). Re-baselining it is a data-owner task; see README "Reproduce Current Committed Outputs".
