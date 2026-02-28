import os
import secrets
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from xero_client import XeroClient
from receipt_generator import generate_receipt_pdf
from email_sender import send_receipt_email

load_dotenv()

app = FastAPI(title="Donation Receipt System")

SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "changeme")

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

templates = Jinja2Templates(directory="templates")

xero = XeroClient(
    client_id=os.environ.get("XERO_CLIENT_ID", ""),
    client_secret=os.environ.get("XERO_CLIENT_SECRET", ""),
    redirect_uri=os.environ.get("XERO_REDIRECT_URI", "http://localhost:8000/auth/callback"),
)


def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")


def require_xero(request: Request):
    if not request.session.get("xero_connected"):
        raise HTTPException(status_code=401, detail="Xero not connected")


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == DASHBOARD_PASSWORD:
        request.session["authenticated"] = True
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Incorrect password"}, status_code=401
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse("/", status_code=302)
    xero_connected = request.session.get("xero_connected", False)
    donations = request.session.get("donations", [])
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "xero_connected": xero_connected,
            "donations": donations,
            "donation_count": len(donations),
        },
    )


# ── Xero OAuth ────────────────────────────────────────────────────────────────

@app.get("/auth/xero")
async def xero_auth(request: Request, _=Depends(require_auth)):
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    auth_url = xero.get_authorization_url(state)
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def xero_callback(request: Request, code: str, state: str):
    if not request.session.get("authenticated"):
        return RedirectResponse("/", status_code=302)
    expected_state = request.session.get("oauth_state")
    if state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    tokens = await xero.exchange_code(code)
    request.session["xero_tokens"] = tokens
    request.session["xero_connected"] = True
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/auth/disconnect")
async def xero_disconnect(request: Request, _=Depends(require_auth)):
    request.session.pop("xero_tokens", None)
    request.session.pop("xero_connected", None)
    request.session.pop("donations", None)
    return RedirectResponse("/dashboard", status_code=302)


# ── Step 2: Pull Donations ────────────────────────────────────────────────────

@app.post("/donations/fetch")
async def fetch_donations(
    request: Request,
    year: int = Form(...),
    account_codes: str = Form(...),
    _=Depends(require_auth),
):
    if not request.session.get("xero_connected"):
        raise HTTPException(status_code=400, detail="Xero not connected")

    tokens = request.session.get("xero_tokens", {})
    codes = [c.strip() for c in account_codes.split(",") if c.strip()]

    try:
        tokens, donations = await xero.get_donations(tokens, year, codes)
        request.session["xero_tokens"] = tokens  # store refreshed tokens
        request.session["donations"] = donations
        request.session["donation_year"] = year
        request.session["account_codes"] = codes
        return RedirectResponse("/dashboard#step2", status_code=302)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Step 3: Review & Send ─────────────────────────────────────────────────────

@app.get("/donations", response_class=JSONResponse)
async def list_donations(request: Request, _=Depends(require_auth)):
    donations = request.session.get("donations", [])
    return JSONResponse(donations)


@app.post("/receipts/send")
async def send_receipts(
    request: Request,
    _=Depends(require_auth),
):
    donations = request.session.get("donations", [])
    year = request.session.get("donation_year", datetime.now().year - 1)

    if not donations:
        raise HTTPException(status_code=400, detail="No donation data. Fetch donations first.")

    results = []
    for donor in donations:
        if not donor.get("email"):
            results.append({"name": donor["name"], "status": "skipped", "reason": "no email"})
            continue
        try:
            pdf_bytes = generate_receipt_pdf(donor, year)
            send_receipt_email(
                to_email=donor["email"],
                donor_name=donor["name"],
                year=year,
                pdf_bytes=pdf_bytes,
            )
            results.append({"name": donor["name"], "email": donor["email"], "status": "sent"})
        except Exception as e:
            results.append({"name": donor["name"], "email": donor.get("email"), "status": "error", "reason": str(e)})

    return JSONResponse({"results": results})


@app.post("/receipts/preview")
async def preview_receipt(request: Request, donor_index: int = Form(...), _=Depends(require_auth)):
    donations = request.session.get("donations", [])
    year = request.session.get("donation_year", datetime.now().year - 1)
    if donor_index < 0 or donor_index >= len(donations):
        raise HTTPException(status_code=404, detail="Donor not found")
    donor = donations[donor_index]
    pdf_bytes = generate_receipt_pdf(donor, year)
    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=receipt_{donor['name'].replace(' ', '_')}.pdf"},
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}
