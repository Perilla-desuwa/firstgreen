import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).resolve().parents[1]
if str(FIXTURE_ROOT) not in sys.path:
    sys.path.insert(0, str(FIXTURE_ROOT))


@pytest.fixture(autouse=True)
def clear_sinks() -> Iterator[None]:
    from app.audit import clear_audit_log
    from app.mailer import clear_outbox

    clear_outbox()
    clear_audit_log()
    yield
    clear_outbox()
    clear_audit_log()
