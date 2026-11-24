# Twenty (CRM)

Checked 2026-11-22. https://docs.twenty.com

- VERIFIED shape: GraphQL at /graphql with a Bearer key. A key is created under Settings, Developers, API.
- UNVERIFIED: the exact createPerson input fields. Introspection can be disabled for API keys, so the adapter keeps field names in one place for you to adjust.
- In this project: tested against a mock (mock/twenty_mock.py). The real field names are unverified.

Contract test: none possible. Docs read 2026-11-23 (https://docs.twenty.com/developers/extend/api) say there is no static API reference; documentation is generated per workspace (Settings, Developers, API) after you create a key, and the page has no example of creating or finding a person. So there is no spec to test against, and the GraphQL field names stay UNVERIFIED until run on a real workspace. See `mock/contracts/twenty/SOURCE.txt`.
