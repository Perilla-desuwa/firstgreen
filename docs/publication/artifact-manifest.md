# Public artifact manifest

The release asset should be named `firstgreen-evidence-VERSION.zip`. Record its SHA-256 in a
sidecar `.sha256` asset and the GitHub Release body. The report points to that sidecar instead of
embedding the hash of an archive that contains the report itself.

## Archive layout

```text
firstgreen-evidence-VERSION/
├── ARTIFACT-METADATA.json
├── SHA256SUMS.txt
├── README.md
├── environment/
│   ├── doctor.txt
│   ├── host.json
│   ├── package-lock.txt
│   └── tool-versions.txt
├── frozen-inputs/
│   ├── public-evidence-plan-v1.md
│   ├── ramsey-v2/
│   ├── tinyshop-s3/
│   ├── javascript-checkout-v1/
│   └── critical-path-ablation/
├── results/
│   ├── scripted/
│   ├── controlled-live-ramsey-v2/
│   ├── controlled-live-tinyshop-s3-luna-v1/
│   ├── javascript-idempotent-checkout-v1/
│   └── critical-path-ablation/
├── figures/
└── report/
    ├── firstgreen-technical-report.pdf
    ├── technical-report.tex
    └── results.tex
```

Each result directory should retain the raw append-only journal, rebuilt summary, sanitized trace,
run-level status/export, and an outcome note. Do not include entire worktrees or unsanitized SQLite
databases merely because they exist locally.

## `ARTIFACT-METADATA.json` required fields

```json
{
  "schema": "firstgreen-public-artifact-v1",
  "release": "0.1.0-rc1",
  "code_commit": "TBD",
  "created_at_utc": "TBD",
  "experiment_protocol": "public-evidence-plan-v1",
  "model": "gpt-5.6-luna",
  "reasoning_effort": "low",
  "host_summary": "TBD",
  "result_classes": ["scripted", "controlled-live", "case-study"],
  "known_missing_cells": [],
  "known_invalid_cells": [],
  "known_failed_cells": []
}
```

`SHA256SUMS.txt` covers every other file in the archive using paths relative to the archive root.
The zip checksum is recorded outside the zip, on the release page and in the report.
