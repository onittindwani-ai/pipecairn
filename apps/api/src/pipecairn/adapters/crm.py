"""CRM adapters. Twenty (tier A, mock tested), HubSpot and Notion (tier B, written from public docs, UNVERIFIED live)."""

from __future__ import annotations

import httpx

from pipecairn.adapters.base import PersonRecord, safe_base_url
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action

FIND_PEOPLE = "query FindPeople($email: String!) { people(filter: {emails: {primaryEmail: {eq: $email}}}) { edges { node { id } } } }"
CREATE_PERSON = "mutation CreatePerson($data: PersonCreateInput!) { createPerson(data: $data) { id } }"


class TwentyCrm:
    """Twenty over GraphQL. Field names are UNVERIFIED against a real workspace: run `tools/doctor.py` with your key, and fix names here if it complains."""

    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        if client is not None:
            self.client = client
        else:
            if not settings.twenty_base_url or not settings.twenty_api_key:
                raise AdapterError("TWENTY_BASE_URL and TWENTY_API_KEY must both be set.")
            self.client = httpx.Client(base_url=safe_base_url(settings.twenty_base_url, allow_private=getattr(settings, "allow_private_base_urls", False)), timeout=15, headers={"Authorization": f"Bearer {settings.twenty_api_key}"})

    def _gql(self, op: str, query: str, variables: dict) -> dict:
        r = self.client.post("/graphql", json={"operationName": op, "query": query, "variables": variables})
        if r.status_code == 401:
            raise AdapterError("Twenty rejected the API key.")
        body = r.json()
        if body.get("errors"):
            raise AdapterError(f"Twenty said: {body['errors'][0].get('message', 'unknown error')}")
        return body["data"]

    @write_action("crm.upsert")
    def upsert_person(self, person: PersonRecord) -> str:
        found = self._gql("FindPeople", FIND_PEOPLE, {"email": person.email})["people"]["edges"]
        if found:
            return str(found[0]["node"]["id"])
        data = {"name": {"firstName": person.first_name, "lastName": person.last_name}, "emails": {"primaryEmail": person.email}, "jobTitle": person.title}
        return str(self._gql("CreatePerson", CREATE_PERSON, {"data": data})["createPerson"]["id"])

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._gql("FindPeople", FIND_PEOPLE, {"email": "healthcheck@example.test"})
            return True, "Twenty answered and accepted the key."
        except AdapterError as exc:
            return False, str(exc)
        except httpx.HTTPError as exc:
            return False, f"Could not reach Twenty: {type(exc).__name__}."


class HubspotCrm:
    """HubSpot CRM v3 contacts (UNVERIFIED live). Needs a private app token with contacts write scope."""

    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        if client is not None:
            self.client = client
        else:
            if not settings.hubspot_token:
                raise AdapterError("HUBSPOT_TOKEN is empty.")
            self.client = httpx.Client(base_url="https://api.hubapi.com", timeout=15, headers={"Authorization": f"Bearer {settings.hubspot_token}"})

    @write_action("crm.upsert")
    def upsert_person(self, person: PersonRecord) -> str:
        props = {"email": person.email, "firstname": person.first_name, "lastname": person.last_name, "jobtitle": person.title}
        if person.phone:
            props["phone"] = person.phone
        r = self.client.post("/crm/v3/objects/contacts", json={"properties": props})
        if r.status_code == 401:
            raise AdapterError("HubSpot rejected the token.")
        if r.status_code == 409:
            return "exists"
        if r.status_code >= 400:
            raise AdapterError(f"HubSpot refused the contact: {r.status_code}")
        return str(r.json()["id"])

    def healthcheck(self) -> tuple[bool, str]:
        try:
            r = self.client.get("/crm/v3/objects/contacts", params={"limit": 1})
        except httpx.HTTPError as exc:
            return False, f"Could not reach HubSpot: {type(exc).__name__}."
        return (r.status_code == 200, "HubSpot answered." if r.status_code == 200 else f"HubSpot answered {r.status_code}. Check the token and its scopes.")


class NotionCrm:
    """Notion pages API (UNVERIFIED live): one page per lead with the name as title. Other columns need your own schema."""

    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        if client is not None:
            self.client = client
        else:
            if not settings.notion_token or not settings.notion_database_id:
                raise AdapterError("NOTION_TOKEN and NOTION_DATABASE_ID must both be set.")
            self.client = httpx.Client(base_url="https://api.notion.com", timeout=15, headers={"Authorization": f"Bearer {settings.notion_token}", "Notion-Version": "2026-03-11"})

    @write_action("crm.upsert")
    def upsert_person(self, person: PersonRecord) -> str:
        title = f"{person.first_name} {person.last_name} ({person.email})".strip()
        body = {"parent": {"database_id": self.settings.notion_database_id}, "properties": {"Name": {"title": [{"text": {"content": title}}]}}}
        r = self.client.post("/v1/pages", json=body)
        if r.status_code == 401:
            raise AdapterError("Notion rejected the token.")
        if r.status_code >= 400:
            raise AdapterError(f"Notion refused the page: {r.status_code}. The database needs a title column named Name and must be shared with the integration.")
        return str(r.json()["id"])

    def healthcheck(self) -> tuple[bool, str]:
        try:
            r = self.client.get(f"/v1/databases/{self.settings.notion_database_id}")
        except httpx.HTTPError as exc:
            return False, f"Could not reach Notion: {type(exc).__name__}."
        return (r.status_code == 200, "Notion answered." if r.status_code == 200 else f"Notion answered {r.status_code}. Share the database with your integration.")
