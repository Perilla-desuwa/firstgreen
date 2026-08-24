from app.mailer import OUTBOX, messages_for, send_email


def test_send_email_appends_to_outbox() -> None:
    sent = send_email("Buyer@Example.Test", "Receipt", "Thanks")
    assert sent["recipient"] == "buyer@example.test"
    assert [sent] == OUTBOX


def test_messages_are_filtered_by_recipient() -> None:
    send_email("one@example.test", "One", "1")
    send_email("two@example.test", "Two", "2")
    assert [item["subject"] for item in messages_for("one@example.test")] == ["One"]


def test_invalid_recipient_is_rejected() -> None:
    try:
        send_email("invalid", "Subject", "Body")
    except ValueError as error:
        assert "email address" in str(error)
    else:
        raise AssertionError("invalid recipient accepted")
