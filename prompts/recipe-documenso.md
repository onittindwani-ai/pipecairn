# Recipe: build a Documenso e-signature adapter (not built, not tested)

The Documenso create document endpoints were not shown to me, so none is claimed. Paste this into Claude Code:

> Read adapters/base.py and adapters/seed.py (SeedEsign) and handoff.py. Look up the current Documenso API documentation (base `https://app.documenso.com/api/v2`, or a self hosted address) and cite the page. Write an adapter `documenso` that creates a document from the contract PDF and sends it for signature, with the same interface as the other e-sign adapters. Sending for signature is a real world write: use `guard_write` and an approval. Add `DOCUMENSO_API_KEY` and `DOCUMENSO_BASE_URL`, check the base URL with `safe_base_url`, test against a local mock you write from the docs, and label every unconfirmed fact UNVERIFIED. Do not call the real service.
