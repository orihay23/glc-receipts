# Donation Receipt System

A web app for nonprofits to pull donor giving data from Xero and automatically generate + email PDF tax receipts.

## Stack

- **Backend**: Python + FastAPI
- **PDF generation**: WeasyPrint (HTML → PDF)
- **Email**: Gmail SMTP (App Password)
- **Hosting**: Render.com free tier
- **Xero integration**: OAuth 2.0, Accounting API

## Setup

### 1. Register a Xero OAuth 2.0 app

1. Go to [developer.xero.com](https://developer.xero.com/app/manage) and create a new app.
2. Set the **OAuth 2.0 redirect URI** to `https://your-app.onrender.com/auth/callback`.
3. Copy the **Client ID** and **Client Secret**.

### 2. Set up Gmail App Password

1. Enable 2-Step Verification on your Google account.
2. Go to [Google Account → Security → App Passwords](https://myaccount.google.com/apppasswords).
3. Generate an App Password for "Mail" and copy it.

### 3. Deploy to Render.com

1. Fork / push this repository to GitHub.
2. Create a new **Web Service** on [render.com](https://render.com), pointing to this repo.
3. Render will detect `render.yaml` automatically.
4. Set the following environment variables in the Render dashboard:

| Variable | Description |
|---|---|
| `DASHBOARD_PASSWORD` | Login password for the web UI |
| `SESSION_SECRET` | Random string for session cookies |
| `XERO_CLIENT_ID` | From developer.xero.com |
| `XERO_CLIENT_SECRET` | From developer.xero.com |
| `XERO_REDIRECT_URI` | `https://your-app.onrender.com/auth/callback` |
| `ORG_NAME` | Your organisation name (appears on receipts) |
| `ORG_ADDRESS` | Street address (optional) |
| `ORG_CHARITY_NUMBER` | Charity registration number (optional) |
| `ORG_EMAIL` | Contact email shown on receipts (optional) |
| `GMAIL_USER` | Gmail address used to send receipts |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your normal password) |

5. After deploy, update the **Redirect URI** in your Xero app to match `XERO_REDIRECT_URI`.

### 4. Run locally (development)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your values

uvicorn main:app --reload
```

Then open [http://localhost:8000](http://localhost:8000).

## Usage

1. **Log in** with your `DASHBOARD_PASSWORD`.
2. **Step 1 — Connect Xero**: Click "Connect Xero" and authorise via Xero's OAuth flow.
3. **Step 2 — Pull data**: Enter the calendar year and the Xero account codes that represent donation income (e.g. `800, 801`). Click "Pull donations".
4. **Step 3 — Review & Send**: Review the donor list and totals, then click "Send all receipts" to email PDF receipts to every donor with an email address on file. Donors without emails are skipped (not errored).

## Notes

- **Stateless** — no database. All data is pulled fresh from Xero each session.
- The free tier on Render.com spins down after inactivity. First load may take ~30 s.
- Xero tokens are stored in the server-side session (encrypted cookie) and expire after 30 minutes; the app refreshes them automatically.
