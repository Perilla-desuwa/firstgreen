# TinyShop

TinyShop is the deterministic Python fixture for the FirstGreen planning and scheduling testbed.
It uses only the standard library, in-memory state, and fake email/audit sinks. The baseline omits
all scenario features intentionally; scenario workers operate only on isolated copies.

```bash
pytest -q
ruff check .
```
