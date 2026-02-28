"""
Xero OAuth 2.0 client and donation data fetcher.

Handles:
- Authorization URL generation
- Code → token exchange
- Token refresh
- Fetching invoices filtered by account codes
- Aggregating donations per contact
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode


XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"

SCOPES = "offline_access accounting.transactions.read accounting.contacts.read openid profile email"


class XeroClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "state": state,
        }
        return f"{XERO_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                XERO_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                auth=(self.client_id, self.client_secret),
            )
            resp.raise_for_status()
            tokens = resp.json()
            tokens["expires_at"] = (
                datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 1800))
            ).isoformat()
            return tokens

    async def _refresh_if_needed(self, tokens: dict) -> dict:
        expires_at = datetime.fromisoformat(tokens.get("expires_at", "2000-01-01"))
        if datetime.utcnow() < expires_at - timedelta(minutes=5):
            return tokens
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                XERO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                },
                auth=(self.client_id, self.client_secret),
            )
            resp.raise_for_status()
            new_tokens = resp.json()
            new_tokens["expires_at"] = (
                datetime.utcnow() + timedelta(seconds=new_tokens.get("expires_in", 1800))
            ).isoformat()
            return new_tokens

    async def _get_tenant_id(self, access_token: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                XERO_CONNECTIONS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            connections = resp.json()
            if not connections:
                raise ValueError("No Xero organisations connected.")
            return connections[0]["tenantId"]

    async def get_donations(
        self, tokens: dict, year: int, account_codes: list[str]
    ) -> tuple[dict, list[dict]]:
        """
        Fetch all PAID invoices for the given calendar year and filter line items
        whose AccountCode is in account_codes. Aggregate by contact.

        Returns (refreshed_tokens, donations) where donations is a list of:
        {
            "name": str,
            "email": str | None,
            "total": float,
            "transactions": [{"date": str, "description": str, "amount": float}],
        }
        """
        tokens = await self._refresh_if_needed(tokens)
        access_token = tokens["access_token"]
        tenant_id = await self._get_tenant_id(access_token)

        from_date = f"{year}-01-01"
        to_date = f"{year}-12-31"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-tenant-id": tenant_id,
            "Accept": "application/json",
        }

        params = {
            "where": f'Status=="PAID" AND Date>=DateTime({year},1,1) AND Date<=DateTime({year},12,31)',
            "page": 1,
        }

        all_invoices = []
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                resp = await client.get(
                    f"{XERO_API_BASE}/Invoices",
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                invoices = data.get("Invoices", [])
                all_invoices.extend(invoices)
                if len(invoices) < 100:
                    break
                params["page"] += 1

        # Fetch contacts once to get emails
        contact_emails = await self._fetch_contact_emails(headers)

        # Aggregate donations by contact
        donors: dict[str, dict] = {}
        account_codes_set = set(account_codes)

        for invoice in all_invoices:
            contact_id = invoice.get("Contact", {}).get("ContactID", "")
            contact_name = invoice.get("Contact", {}).get("Name", "Unknown")
            invoice_date = invoice.get("DateString", "")[:10]

            for line in invoice.get("LineItems", []):
                code = line.get("AccountCode", "")
                if code not in account_codes_set:
                    continue
                amount = float(line.get("LineAmount", 0))
                if amount <= 0:
                    continue
                description = line.get("Description", "Donation")

                if contact_id not in donors:
                    donors[contact_id] = {
                        "name": contact_name,
                        "email": contact_emails.get(contact_id),
                        "total": 0.0,
                        "transactions": [],
                    }
                donors[contact_id]["total"] = round(donors[contact_id]["total"] + amount, 2)
                donors[contact_id]["transactions"].append(
                    {"date": invoice_date, "description": description, "amount": amount}
                )

        # Sort transactions within each donor by date
        donations = []
        for donor in donors.values():
            donor["transactions"].sort(key=lambda t: t["date"])
            donations.append(donor)

        donations.sort(key=lambda d: d["name"])
        return tokens, donations

    async def _fetch_contact_emails(self, headers: dict) -> dict[str, Optional[str]]:
        emails: dict[str, Optional[str]] = {}
        page = 1
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                resp = await client.get(
                    f"{XERO_API_BASE}/Contacts",
                    headers=headers,
                    params={"page": page, "includeArchived": False},
                )
                if resp.status_code != 200:
                    break
                contacts = resp.json().get("Contacts", [])
                for c in contacts:
                    cid = c.get("ContactID", "")
                    email = c.get("EmailAddress") or None
                    emails[cid] = email
                if len(contacts) < 100:
                    break
                page += 1
        return emails
