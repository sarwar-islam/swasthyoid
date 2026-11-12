"""Real OCR adapters live here — none exists.

The project owner trains, owns and supplies the OCR model. A model-specific adapter is added
only after the owner supplies the trained model and its specification and explicitly approves
the integration (docs/DECISIONS.md, D4, D17, D18). Only modules in this package may import a
model runtime or ML framework (tests/test_import_allowlist.py).
"""
