"""SOAP client for the AzerothCore worldserver.

Sends GM console commands via the ``ns1__executeCommand`` SOAP endpoint
running on port 7878.  Uses raw XML over HTTP (no WSDL dependency).
"""

from __future__ import annotations

import httpx
import structlog

from core.config import settings

logger = structlog.get_logger()

_SOAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope
  xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:ns1="urn:AC">
  <SOAP-ENV:Body>
    <ns1:executeCommand>
      <command>$COMMAND$</command>
    </ns1:executeCommand>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


class SoapClient:
    """Async SOAP client for AzerothCore GM console commands."""

    def __init__(self) -> None:
        self._url = f"http://{settings.ws_host}:{settings.ws_soap_port}/"
        self._auth = (settings.soap_user, settings.soap_pass)
        self._client = httpx.AsyncClient(timeout=10.0)

    async def execute(self, command: str) -> str:
        """Execute a GM console command and return the response text."""
        # Escape XML special chars in the command string
        safe_command = (
            command.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
        # Use simple string replacement to avoid str.format() issues with { }
        body = _SOAP_TEMPLATE.replace("$COMMAND$", safe_command)

        try:
            resp = await self._client.post(
                self._url,
                content=body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                auth=self._auth,
            )
            resp.raise_for_status()
            # Extract the result text from the SOAP response envelope
            text = resp.text
            start = text.find("<result>")
            end = text.find("</result>")
            if start != -1 and end != -1:
                return text[start + 8 : end]
            return text
        except httpx.HTTPError as exc:
            logger.error("soap.execute_failed", command=command, error=str(exc))
            return ""

    async def bot_command(self, bot_name: str, command: str) -> str:
        """Send a playerbot-specific command via the SOAP console."""
        return await self.execute(f"bot {bot_name} {command}")

    async def close(self) -> None:
        await self._client.aclose()
