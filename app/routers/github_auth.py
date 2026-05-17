import hashlib
import hmac
import json
import os
import urllib.parse

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, EmailStr

from app.config import settings
from app.core.responses import ok
from app.deps import current_user, get_auth_service
from app.models.user import User
from app.schemas.auth import RefreshRequest, TokenResponse
from app.schemas.response import ApiResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth/github", tags=["auth"])

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_COOKIE_NAME = "oauth_nonce"
_COOKIE_MAX_AGE = 600


def _sign_nonce(nonce: str) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode(),
        nonce.encode(),
        hashlib.sha256,
    ).hexdigest()


def _make_state(nonce: str) -> str:
    return f"{nonce}.{_sign_nonce(nonce)}"


def _verify_state(state: str, cookie_nonce: str) -> bool:
    try:
        nonce, sig = state.rsplit(".", 1)
    except ValueError:
        return False
    sig_ok = hmac.compare_digest(_sign_nonce(nonce), sig)
    nonce_ok = hmac.compare_digest(nonce, cookie_nonce)
    return sig_ok and nonce_ok


@router.get("")
async def github_authorize(response: Response):
    nonce = os.urandom(16).hex()
    state = _make_state(nonce)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": "read:user user:email",
        "state": state,
    }
    redirect = RedirectResponse(f"{_GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}")
    redirect.set_cookie(
        _COOKIE_NAME,
        nonce,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
    )
    return redirect


@router.get("/callback", response_class=HTMLResponse)
async def github_callback(
    code: str,
    state: str,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    oauth_nonce: str | None = Cookie(default=None, alias=_COOKIE_NAME),
):
    if not oauth_nonce or not _verify_state(state, oauth_nonce):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="OAuth state không hợp lệ — có thể là tấn công CSRF")

    _secure = settings.app_env != "development"
    response.delete_cookie(_COOKIE_NAME, httponly=True, samesite="lax", secure=_secure)

    access_token, refresh_token = await service.process_github_callback(code)
    target_origin = settings.cors_origins[0] if settings.cors_origins else "*"
    payload = json.dumps({
        "type": "github_oauth",
        "access_token": access_token,
        "refresh_token": refresh_token,
    })
    html = f"""<!doctype html><html><body><script>
window.opener && window.opener.postMessage({payload}, {json.dumps(target_origin)});
window.close();
</script><p>Đang đóng cửa sổ...</p></body></html>"""
    return HTMLResponse(html)


@router.post("/refresh", response_model=ApiResponse[TokenResponse])
async def refresh(
    body: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
):
    access_token, refresh_token = await service.refresh_tokens(body.refresh_token)
    return ok(TokenResponse(access_token=access_token, refresh_token=refresh_token))


class DevLoginRequest(BaseModel):
    email: EmailStr


@router.post("/dev-login", response_model=ApiResponse[TokenResponse], include_in_schema=settings.app_env == "development")
async def dev_login(
    body: DevLoginRequest,
    service: AuthService = Depends(get_auth_service),
):
    if settings.app_env != "development":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    user = await service.get_user_for_dev_login(body.email)
    access_token, refresh_token = service.create_token_pair(user)
    return ok(TokenResponse(access_token=access_token, refresh_token=refresh_token))


@router.delete("/unlink", status_code=status.HTTP_204_NO_CONTENT)
async def github_unlink(
    user: User = Depends(current_user),
    service: AuthService = Depends(get_auth_service),
):
    await service.unlink_github(user)
