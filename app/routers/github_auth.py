import asyncio
import hashlib
import hmac
import os
import urllib.parse
import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.core.security import create_access_token, create_refresh_token
from app.core.crypto import encrypt_token
from app.schemas.auth import TokenResponse
from app.schemas.response import ApiResponse
from app.core.responses import ok
from app.deps import current_user
from app.config import settings

router = APIRouter(prefix="/auth/github", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"

_COOKIE_NAME = "oauth_nonce"
_COOKIE_MAX_AGE = 600  # 10 minutes


def _sign_nonce(nonce: str) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode(),
        nonce.encode(),
        hashlib.sha256,
    ).hexdigest()


def _make_state(nonce: str) -> str:
    """state = <nonce>.<hmac> — verifiable without server storage."""
    return f"{nonce}.{_sign_nonce(nonce)}"


def _verify_state(state: str, cookie_nonce: str) -> bool:
    """Verify HMAC signature AND that the state matches the cookie nonce (single-use via cookie deletion)."""
    try:
        nonce, sig = state.rsplit(".", 1)
    except ValueError:
        return False
    expected = _sign_nonce(nonce)
    sig_ok = hmac.compare_digest(expected, sig)
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
    redirect = RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}")
    # httpOnly cookie stores the nonce; browser sends it back on callback
    redirect.set_cookie(
        _COOKIE_NAME,
        nonce,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
    )
    return redirect


@router.get("/callback", response_model=ApiResponse[TokenResponse])
async def github_callback(
    code: str,
    state: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    oauth_nonce: str | None = Cookie(default=None, alias=_COOKIE_NAME),
):
    if not oauth_nonce or not _verify_state(state, oauth_nonce):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state — possible CSRF attack")

    # Consume nonce immediately — attributes must mirror set_cookie exactly so browsers honor the deletion
    _secure = settings.app_env != "development"
    response.delete_cookie(_COOKIE_NAME, httponly=True, samesite="lax", secure=_secure)

    async with httpx.AsyncClient() as client:
        try:
            token_resp = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": settings.github_redirect_uri,
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
            token_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"GitHub token exchange failed: {exc.response.status_code}")
        except httpx.RequestError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="GitHub unreachable")

    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="GitHub OAuth failed: no access token returned")

    gh_headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}

    async with httpx.AsyncClient() as client:
        try:
            user_data, emails_data = await asyncio.gather(
                client.get(GITHUB_USER_URL, headers=gh_headers, timeout=10),
                client.get(GITHUB_EMAILS_URL, headers=gh_headers, timeout=10),
            )
            user_data.raise_for_status()
            emails_data.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"GitHub API error: {exc.response.status_code}")
        except httpx.RequestError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="GitHub unreachable")

    gh_user = user_data.json()
    emails = emails_data.json()

    # Require a verified primary email — never trust unverified or synthesized addresses
    verified_primary = next(
        (e["email"] for e in emails if e.get("verified") and e.get("primary")),
        None,
    )
    if not verified_primary:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="GitHub account has no verified primary email. Add and verify an email on GitHub before linking.",
        )

    github_id = str(gh_user["id"])
    github_login = gh_user.get("login")
    github_avatar_url = gh_user.get("avatar_url")
    encrypted_token = encrypt_token(access_token)

    result = await db.execute(select(User).where(User.github_id == github_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == verified_primary))
        user = result.scalar_one_or_none()

    if user:
        user.github_id = github_id
        user.github_login = github_login
        user.github_avatar_url = github_avatar_url
        user.github_access_token = encrypted_token
    else:
        user = User(
            email=verified_primary,
            github_id=github_id,
            github_login=github_login,
            github_avatar_url=github_avatar_url,
            github_access_token=encrypted_token,
            full_name=gh_user.get("name"),
        )
        db.add(user)

    await db.flush()
    access_token = create_access_token(str(user.id), user.role)
    refresh_token = create_refresh_token(str(user.id))
    # Popup pattern: trả HTML tự postMessage token về opener rồi đóng
    html = f"""<!doctype html><html><body><script>
window.opener && window.opener.postMessage(
  {{"type":"github_oauth","access_token":"{access_token}","refresh_token":"{refresh_token}"}},
  "*"
);
window.close();
</script><p>Đang đóng cửa sổ...</p></body></html>"""
    return HTMLResponse(html)


@router.delete("/unlink", status_code=status.HTTP_204_NO_CONTENT)
async def github_unlink(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not user.hashed_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot unlink GitHub: no password set on account")
    user.github_id = None
    user.github_login = None
    user.github_avatar_url = None
    user.github_access_token = None
    await db.flush()
