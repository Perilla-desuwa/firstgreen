# Add password reset

Add a password-reset workflow.

A user can request a reset token. The token expires after one hour. The system sends a fake email containing the token. A confirmation operation validates the token and updates the user's password, or a deterministic password representation used by the fixture. Invalid and expired tokens must be rejected. Add focused unit and integration tests.
