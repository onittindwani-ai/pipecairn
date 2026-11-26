# SMTP and IMAP (email)

Checked 2026-11-23. These are protocols (RFC 5321 SMTP, RFC 5322 message format, RFC 3501 IMAP4rev1), not a web API, so there is no OpenAPI or other machine readable contract.

- The adapter uses the Python standard library (`smtplib`, `imaplib`, `email`), which implements the protocols. It does not write protocol text by hand.
- Tested against local mock servers (`mock/mail_servers.py`) and by a contract style test that a built message has the RFC 5322 header fields (`apps/api/tests/test_contracts.py`).
- UNVERIFIED: any real mail host. Gmail needs an app password; Outlook and others differ. The RFC page fetch returned only part of RFC 3501, so no IMAP example was saved (`mock/contracts/smtp_imap/SOURCE.txt`).
