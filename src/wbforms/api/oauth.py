"""OAuth login flow against a Wikibase instance.

Supports two OAuth versions, selected by the ``WBFORMS_OAUTH_VERSION`` setting:

* ``"2.0"`` — Wikibase REST ``/oauth2/*`` authorization-code grant. Used by
  wikibase.cloud-hosted instances such as ceur-dev.
* ``"1.0a"`` — MediaWiki ``Special:OAuth/*`` 3-legged flow. Used by classic
  MediaWiki deployments such as FactGrid.

Exposes two endpoints:

* ``GET /oauth/login`` — starts the appropriate authorization flow.
* ``GET /oauth/callback`` — completes the flow, builds a user-bound
  :class:`WikibaseSession`, stores it in the session store, and redirects the
  SPA with the session token in the URL fragment.
"""

import asyncio
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from requests_oauthlib import OAuth1Session

from wbforms.api.auth import (
    consume_oauth_state,
    consume_request_token,
    issue_oauth_state,
    register_session,
    remember_request_token,
)
from wbforms.datamodel.auth import WikibaseOauth1, WikibaseUserOAuth2
from wbforms.session import WikibaseSession
from wbforms.settings import get_settings
from wbforms.wikibase import get_default_user_agent

router = APIRouter(prefix="/oauth", tags=["Authentication"])


def _rest_base() -> str:
    return get_settings().wikibase_mediawiki_rest_url.unicode_string().rstrip("/")


def _index_php_base() -> str:
    """MediaWiki ``index.php`` URL, derived from the configured API URL."""
    api_url = get_settings().wikibase_mediawiki_api_url.unicode_string()
    return api_url.rsplit("/", 1)[0] + "/index.php"


def _require_oauth_config() -> tuple[str, str, str]:
    settings = get_settings()
    if not settings.oauth_client_id or not settings.oauth_client_secret or not settings.oauth_redirect_uri:
        raise HTTPException(
            status_code=503,
            detail=(
                "OAuth is not configured. Set WBFORMS_OAUTH_CLIENT_ID, "
                "WBFORMS_OAUTH_CLIENT_SECRET, and WBFORMS_OAUTH_REDIRECT_URI."
            ),
        )
    return (
        settings.oauth_client_id,
        settings.oauth_client_secret.get_secret_value(),
        settings.oauth_redirect_uri.unicode_string(),
    )


@router.get("/login")
async def oauth_login() -> RedirectResponse:
    """Start the configured OAuth authorization flow."""
    if get_settings().oauth_version == "1.0a":
        return await _oauth1_login()
    return await _oauth2_login()


@router.get("/callback")
async def oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    oauth_token: str | None = Query(None),
    oauth_verifier: str | None = Query(None),
) -> RedirectResponse:
    """Complete the configured OAuth flow and create a session."""
    if get_settings().oauth_version == "1.0a":
        if not oauth_token or not oauth_verifier:
            raise HTTPException(status_code=400, detail="Missing oauth_token / oauth_verifier")
        return await _oauth1_callback(oauth_token, oauth_verifier)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code / state")
    return await _oauth2_callback(code, state)


# --- OAuth 2.0 -------------------------------------------------------------


async def _oauth2_login() -> RedirectResponse:
    client_id, _client_secret, redirect_uri = _require_oauth_config()
    state = issue_oauth_state()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return RedirectResponse(url=f"{_rest_base()}/oauth2/authorize?{urlencode(params)}", status_code=302)


async def _oauth2_callback(code: str, state: str) -> RedirectResponse:
    client_id, client_secret, redirect_uri = _require_oauth_config()
    if not consume_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    token_url = f"{_rest_base()}/oauth2/access_token"
    profile_url = f"{_rest_base()}/oauth2/resource/profile"
    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": get_default_user_agent()}
    ) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"OAuth token exchange failed: {resp.text}")
        payload = resp.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="OAuth token exchange returned no access_token")

        username = "oauth2-user"
        try:
            profile_resp = await client.get(profile_url, headers={"Authorization": f"Bearer {access_token}"})
            if profile_resp.status_code == 200:
                username = profile_resp.json().get("username") or username
        except httpx.HTTPError:
            pass

    auth = WikibaseUserOAuth2(
        access_token=access_token,
        refresh_token=payload.get("refresh_token"),
        client_id=client_id,
        client_secret=client_secret,
    )
    return _finalize_login(auth, username)


# --- OAuth 1.0a ------------------------------------------------------------


async def _oauth1_login() -> RedirectResponse:
    client_id, client_secret, _redirect_uri = _require_oauth_config()
    initiate_url = f"{_index_php_base()}?title=Special:OAuth/initiate"

    def _fetch() -> dict:
        # MediaWiki uses the callback URL registered with the consumer, so the
        # client always passes the literal "oob" here per the OAuth/initiate spec.
        session = OAuth1Session(client_key=client_id, client_secret=client_secret, callback_uri="oob")
        session.headers.update({"User-Agent": get_default_user_agent()})
        return session.fetch_request_token(initiate_url)

    try:
        token = await asyncio.to_thread(_fetch)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth request-token fetch failed: {e}") from e

    request_token = token.get("oauth_token")
    request_secret = token.get("oauth_token_secret")
    if not request_token or not request_secret:
        raise HTTPException(status_code=400, detail="OAuth request-token response missing tokens")

    remember_request_token(request_token, request_secret)
    authorize_url = f"{_index_php_base()}?title=Special:OAuth/authorize&oauth_token={request_token}"
    return RedirectResponse(url=authorize_url, status_code=302)


async def _oauth1_callback(oauth_token: str, oauth_verifier: str) -> RedirectResponse:
    client_id, client_secret, _redirect_uri = _require_oauth_config()
    request_secret = consume_request_token(oauth_token)
    if request_secret is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth request token")

    token_url = f"{_index_php_base()}?title=Special:OAuth/token"

    def _exchange() -> dict:
        session = OAuth1Session(
            client_key=client_id,
            client_secret=client_secret,
            resource_owner_key=oauth_token,
            resource_owner_secret=request_secret,
            verifier=oauth_verifier,
        )
        session.headers.update({"User-Agent": get_default_user_agent()})
        return session.fetch_access_token(token_url)

    try:
        access = await asyncio.to_thread(_exchange)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth access-token exchange failed: {e}") from e

    access_token = access.get("oauth_token")
    access_secret = access.get("oauth_token_secret")
    if not access_token or not access_secret:
        raise HTTPException(status_code=400, detail="OAuth access-token response missing tokens")

    username = await asyncio.to_thread(_oauth1_identify, client_id, client_secret, access_token, access_secret)

    auth = WikibaseOauth1(
        consumer_token=client_id,
        consumer_secret=client_secret,
        access_token=access_token,
        access_secret=access_secret,
    )
    return _finalize_login(auth, username)


def _oauth1_identify(client_id: str, client_secret: str, access_token: str, access_secret: str) -> str:
    """Resolve the username via MediaWiki's ``Special:OAuth/identify`` JWS endpoint.

    Best-effort: returns ``"oauth1-user"`` if the request or decode fails, mirroring
    the 2.0 path's handling of profile-fetch errors.
    """
    identify_url = f"{_index_php_base()}?title=Special:OAuth/identify"
    try:
        session = OAuth1Session(
            client_key=client_id,
            client_secret=client_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_secret,
        )
        session.headers.update({"User-Agent": get_default_user_agent()})
        resp = session.get(identify_url, timeout=15.0)
        if resp.status_code != 200:
            return "oauth1-user"
        # MediaWiki returns a JWS signed with HS256 using the consumer secret.
        # Signature is already trusted (HTTPS to the same wiki we just authed against),
        # so decode without verification to read the username claim.
        claims = jwt.decode(resp.text, options={"verify_signature": False})
        return claims.get("username") or "oauth1-user"
    except Exception:
        return "oauth1-user"


# --- shared ---------------------------------------------------------------


def _finalize_login(auth, username: str) -> RedirectResponse:
    session = WikibaseSession(auth)
    # Eagerly resolve the wbi login so we fail loudly here if the token is bad,
    # rather than on the user's first edit.
    session.get_wbi_login()
    session_token = register_session(session, subject=username)

    app_base = get_settings().app_base_url.unicode_string().rstrip("/")
    return RedirectResponse(url=f"{app_base}/#token={session_token}", status_code=302)
