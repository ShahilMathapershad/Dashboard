"""Top-level Dash app wiring (split from the original 1619-line app.py).

Each module exposes `register(app)` that the entry-point app.py calls.
For now (Wave 2) only `cache_callbacks` lives here, alongside the legacy
callbacks still inside app.py. Wave 4 deletes the legacy chain.
"""
