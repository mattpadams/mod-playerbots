"""Anthropic OAuth token management.

Reads credentials from the host's Claude Code CLI credentials file,
which is volume-mounted into the container at /app/credentials.json.
Handles token refresh via file reload or OAuth endpoint.
"""
import json
import logging
import os
import time
from pathlib import Path

import httpx

from providers.auth.base import AuthManager

logger = logging.getLogger("llm_bots.auth")

CREDENTIALS_FILE = Path("/app/credentials.json")
TOKEN_ENDPOINT = "https://console.anthropic.com/v1/oauth/token"


class ClaudeAuthManager(AuthManager):
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0
        self.load_credentials()

    def load_credentials(self):
        if not CREDENTIALS_FILE.exists():
            logger.warning("No credentials file found at %s", CREDENTIALS_FILE)
            return
        try:
            creds = json.loads(CREDENTIALS_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to read credentials: %s", e)
            return
        oauth = creds.get("claudeAiOauth", {})
        self.access_token = oauth.get("accessToken")
        self.refresh_token = oauth.get("refreshToken")
        self.expires_at = oauth.get("expiresAt", 0)
        if self.access_token:
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = self.access_token
            expires_in = (self.expires_at - time.time() * 1000) / 1000 / 60
            logger.info("Loaded OAuth token (expires in %.1f min)", expires_in)

    def is_expired(self):
        return time.time() * 1000 >= self.expires_at - 300_000

    async def refresh(self) -> bool:
        # Strategy 1: Reload credentials file (CLI may have refreshed it)
        old_token = self.access_token
        self.load_credentials()
        if self.access_token and self.access_token != old_token and not self.is_expired():
            logger.info("Token refreshed via credentials file reload")
            return True

        # Strategy 2: Call the OAuth refresh endpoint
        if not self.refresh_token:
            logger.error("No refresh token available")
            return False

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                resp = await client.post(
                    TOKEN_ENDPOINT,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code >= 400:
                    resp = await client.post(
                        TOKEN_ENDPOINT,
                        json={
                            "grant_type": "refresh_token",
                            "refresh_token": self.refresh_token,
                        },
                    )
                if resp.status_code >= 400:
                    logger.error(
                        "Token refresh failed (%d): %s",
                        resp.status_code, resp.text[:200],
                    )
                    return False

                data = resp.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token", self.refresh_token)
                expires_in = data.get("expires_in", 3600)
                self.expires_at = int(time.time() * 1000) + expires_in * 1000
                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = self.access_token
                logger.info("Token refreshed via API (expires in %.1f min)", expires_in / 60)
                return True
        except Exception as e:
            logger.error("Token refresh failed: %s", e)
            return False

    async def ensure_valid_token(self):
        if self.is_expired():
            logger.info("Token expired or expiring soon, refreshing...")
            success = await self.refresh()
            if not success:
                logger.error(
                    "Token refresh failed. Run 'claude login' on host to re-authenticate."
                )
        return self.access_token
