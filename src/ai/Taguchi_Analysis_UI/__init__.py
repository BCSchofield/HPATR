"""Taguchi_Analysis_UI — batch orchestrator and generalised Taguchi analyser.

A thin PySide6 front end over the canonical droplet-measurement pipeline in
AI/Real_Data_Code/. This package contains NO measurement logic of its own:
every stage, flag and output path it relies on is declared once in
`pipeline_spec.py` and verified against the real scripts at startup (see
`pipeline_spec.preflight()`). If the pipeline's CLI changes, this app is
designed to fail loudly, not to silently do the wrong thing.

Run with:
    python -m src.ai.Taguchi_Analysis_UI
"""
