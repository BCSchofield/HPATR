"""Flow Visualisation, Phase 1 (2026-10-23): where droplets of each size go in the atomisation chamber.

One-way particle tracking through an idealised airflow (textbook jets added together), with the droplet physics
that Phase 3 reuses unchanged in the real chamber flow. Plan: `Flow Visualisation/PLAN.md`.

Modules: physics (gas, drag, the integrator, jet momentum), settings (the YAML scenario), flow (the jets), injection
(the droplets fired), tracker (the integration and each droplet's fate), sizes (the measured size distribution),
analysis (delivery, purity, deflection), plots, report, run (one scenario or a sweep).
"""
__version__ = "1.0.0"
