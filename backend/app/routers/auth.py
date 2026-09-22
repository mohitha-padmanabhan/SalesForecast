from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
import msal
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
    auth_url = msal_app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=settings.AZURE_MS_AUTH_REDIRECT_URI
    )
    return RedirectResponse(url=auth_url)

@router.get("/callback")
def microsoft_callback(code: str = Query(None), error: str = Query(None)):
    """Handles callback from Microsoft at http://localhost:8000/auth/callback"""
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

    # Redirect user back to React login page with success status, user name, and user email
    redirect_target = (
        f"{settings.FRONTEND_URL}/login"
        f"?login_success=true&user={user_name}&email={user_email}"
    )
    return RedirectResponse(url=redirect_target)