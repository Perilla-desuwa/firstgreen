# Fix invalid order page size

Fix order pagination so that `page_size=0` no longer causes a division-by-zero or equivalent internal error. Any `page_size` smaller than 1 must produce a clear parameter validation error. Add focused regression tests for zero and negative page sizes while preserving normal pagination behavior.
