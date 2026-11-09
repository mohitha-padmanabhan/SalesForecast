from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
import msal
import secrets
import hmac
import os
from urllib.parse import urlencode
from pydantic import BaseModel
from app.services import state_locks
from app.config import settings

# Router prefix set to /auth so the full path becomes /auth/callback
router = APIRouter(prefix="/auth", tags=["Authentication"])

SCOPES = ["User.Read"]

def _build_msal_app():
    authority = f"https://login.microsoftonline.com/{settings.AZURE_MS_AUTH_TENANT_ID}"
    return msal.ConfidentialClientApplication(
        settings.AZURE_MS_AUTH_CLIENT_ID,
        client_credential=settings.AZURE_MS_AUTH_CLIENT_SECRET,
        authority=authority
    )

@router.get("/microsoft/login")
def microsoft_login():
    """Redirects user to Microsoft sign-in page."""
    if not settings.AZURE_MS_AUTH_CLIENT_ID or not settings.AZURE_MS_AUTH_CLIENT_SECRET:
        raise HTTPException(
            status_code=500, 
            detail="Microsoft SSO credentials (AZURE_MS_AUTH_*) are missing in configuration."
        )

    msal_app = _build_msal_app()
    oauth_state = secrets.token_urlsafe(32)
    auth_url = msal_app.get_authorization_request_url(
        scopes=SCOPES,
        state=oauth_state,
        redirect_uri=settings.AZURE_MS_AUTH_REDIRECT_URI
    )
    response = RedirectResponse(url=auth_url)
    response.set_cookie('forecast_oauth_state', oauth_state, httponly=True, samesite='lax', max_age=600, secure=settings.FRONTEND_URL.startswith('https://'))
    return response

@router.get("/callback")
def microsoft_callback(request: Request, code: str = Query(None), error: str = Query(None), state: str = Query(None)):
    """Handles callback from Microsoft at http://localhost:8000/auth/callback"""
    expected_state = request.cookies.get('forecast_oauth_state', '')
    if not state or not expected_state or not hmac.compare_digest(state, expected_state):
        raise HTTPException(400, 'Sign-in session expired. Please sign in again.')
    if error or not code:
        raise HTTPException(
            status_code=400, 
            detail=f"Authentication error: {error or 'No authorization code provided'}"
        )

    msal_app = _build_msal_app()
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=settings.AZURE_MS_AUTH_REDIRECT_URI
    )

    if "error" in result:
        raise HTTPException(
            status_code=400, 
            detail=result.get("error_description", "Failed to acquire token from Microsoft.")
        )

    # Extract user information from ID token claims
    user_info = result.get("id_token_claims", {})
    user_name = user_info.get("name", "User")
    # Microsoft Entra ID usually provides email in 'preferred_username' or 'email'
    user_email = user_info.get("preferred_username") or user_info.get("email", "")

    if not user_email:
        raise HTTPException(400, 'Your Microsoft account did not provide an email address.')
    response = RedirectResponse(settings.FRONTEND_URL + '/login?' + urlencode({
        'login_success': 'true', 'user': user_name, 'email': user_email
    }))
    set_session_cookie(response, state_locks.issue_session(user_email))
    response.delete_cookie('forecast_oauth_state')
    return response


def set_session_cookie(response, token):
    response.set_cookie(state_locks.COOKIE, token, httponly=True, samesite='lax', max_age=28800,
                        secure=settings.FRONTEND_URL.startswith('https://'))

class DemoLogin(BaseModel):
    username: str
    password: str

@router.post('/demo-login')
def demo_login(payload: DemoLogin, response: Response):
    if not hmac.compare_digest(payload.username, 'admin') or not hmac.compare_digest(payload.password, os.environ.get('FORECAST_DEMO_PASSWORD', 'password')):
        raise HTTPException(401, 'Invalid username or password')
    email = 'admin@demo.local'
    set_session_cookie(response, state_locks.issue_session(email))
    return {'email': email, 'name': 'Admin'}

@router.get('/session')
def current_session(request: Request):
    _, email = state_locks.identity(request)
    return {'email': email}

@router.post('/logout')
def logout(request: Request, response: Response):
    state_locks.logout(request)
    response.delete_cookie(state_locks.COOKIE)
    return {'signed_out': True}
