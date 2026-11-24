# Telnyx (texting)

Checked 2026-11-22. https://developers.telnyx.com

- VERIFIED: send with POST /v2/messages, Bearer auth, body to, text, from. The reply has data.id.
- VERIFIED: inbound webhooks carry telnyx-signature-ed25519 and telnyx-timestamp. The signed string is the timestamp, a pipe, then the raw body. Reject anything older than 5 minutes.
- UNVERIFIED: the portal path to the public key (a third party said Account Settings, Keys and Credentials) and the steps to create an API key.
- Your own job, not the software's: US carriers require registering your brand and campaign (10DLC) before business texts are delivered. Pipecairn does not do this for you. See docs/14.
- In this project: tested against a mock written from these docs (mock/telnyx_mock.py), including a real Ed25519 signature. Never run against the real service.

Contract test (round 4, 2026-11-23): `apps/api/tests/test_contracts.py` checks the adapter against field lists read from the send page and the inbound webhook page (`mock/contracts/telnyx/`): only documented request fields are sent, the `data.id` and error `detail` are read, the inbound payload paths match, and the signature is timestamp, a pipe and the raw body with a 5 minute limit. Telnyx publishes an OpenAPI repository, but the page fetch tool could not return the spec file, so this is a field list test, not a test against the spec file.
