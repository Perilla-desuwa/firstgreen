"""Deterministic in-memory email delivery."""

from dataclasses import dataclass

OUTBOX: list[dict[str, str]] = []


@dataclass(frozen=True)
class Email:
    recipient: str
    subject: str
    body: str

    def as_record(self) -> dict[str, str]:
        return {"recipient": self.recipient, "subject": self.subject, "body": self.body}


def send_email(recipient: str, subject: str, body: str) -> dict[str, str]:
    """Append an email to the fake outbox and return a copy."""
    if "@" not in recipient:
        raise ValueError("recipient must be an email address")
    if not subject.strip():
        raise ValueError("subject cannot be empty")
    message = Email(recipient.strip().lower(), subject.strip(), body)
    record = message.as_record()
    OUTBOX.append(record)
    return dict(record)


def messages_for(recipient: str) -> list[dict[str, str]]:
    normalized = recipient.strip().lower()
    return [dict(message) for message in OUTBOX if message["recipient"] == normalized]


def clear_outbox() -> None:
    OUTBOX.clear()
