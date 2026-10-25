# QCB5 DOT Safety: AGENTS.md

**Ops:** `~/sites/electoralanalytics-site/docs/ops.md`. Read `README.md` for pipeline.
Orientation for AI agents. Read `README.md`. **Reproduce outputs from committed `data_raw/` before changing methodology.**

## Standards (shared)

- Style: `~/sites/electoralanalytics-site/docs/style/README.md`

## What this is

Approval-rate analysis of NYC DOT safety requests in Queens CB5 (signals, speed reducers, crashes). Site slug: `qcb5-dot-safety`. Site layout: `analysis`.

## Data provenance

Signal studies `w76s-c5u4`, SRTS `9n6h-pt9g`, crashes `h9gi-nx95` (+ others in fetch script). CB5 polygon is sole geographic authority for coordinate-bearing layers.

## Pipeline

```bash
source .venv/bin/activate
python generate_charts.py && python generate_maps.py
python scripts_validate_outputs.py
python -m unittest discover -s tests
```

## Deployment

**`main` is the live branch.** Publish updates via `npm run publish:project -- qcb5-dot-safety` from `electoralanalytics-site` (see `publish/projects/qcb5-dot-safety.json` and `_build/fetch-maps.sh`).
