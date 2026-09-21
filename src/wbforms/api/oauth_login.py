"""Wikibase OAuth 2.0 user-delegated login adapter for wikibaseintegrator.

``wikibaseintegrator.wbi_login.OAuth2`` only implements the client-credentials
grant. To make edits in the name of an end user we need to drive
``wbi_login._Login`` with a session that carries the user's previously
obtained authorization-code access token.
"""

from requests_oauthlib import OAuth2Session
from wikibaseintegrator.wbi_login import _Login
from wbforms.wikibase import get_default_user_agent


class UserOAuth2(_Login):
    """A wbi login that authenticates with a user OAuth 2.0 access token."""

    def __init__(
        self,
        access_token: str,
        mediawiki_api_url: str,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        mediawiki_rest_url: str | None = None,
        token_renew_period: int = 1800,
        user_agent: str | None = None,
    ):
        token = {"access_token": access_token, "token_type": "Bearer"}
        if refresh_token:
            token["refresh_token"] = refresh_token

        auto_refresh_url = (
            f"{mediawiki_rest_url}/oauth2/access_token" if (refresh_token and mediawiki_rest_url) else None
        )
        session = OAuth2Session(
            client_id=client_id,
            token=token,
            auto_refresh_url=auto_refresh_url,
            auto_refresh_kwargs={"client_id": client_id, "client_secret": client_secret} if auto_refresh_url else {},
            token_updater=lambda _t: None,
        )
        session.headers.update({"User-Agent": get_default_user_agent()})
        super().__init__(
            session=session,
            mediawiki_api_url=mediawiki_api_url,
            token_renew_period=token_renew_period,
            user_agent=user_agent,
        )
