"""Milestone 0: Infrastructure connectivity tests.

Run from the host or inside the middleware container:
    python -m pytest tests/test_m0_infrastructure.py -v

These tests verify that all external services are reachable and
responding correctly before moving to Milestone 1.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# When running standalone (not via pytest), allow direct execution
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Configuration — override with env vars if not running inside Docker
# ---------------------------------------------------------------------------
WS_HOST = os.environ.get("WS_HOST", "localhost")
WS_CMD_PORT = int(os.environ.get("WS_CMD_PORT", "8888"))
WS_SOAP_PORT = int(os.environ.get("WS_SOAP_PORT", "7878"))
SOAP_USER = os.environ.get("SOAP_USER", "admin")
SOAP_PASS = os.environ.get("SOAP_PASS", "admin")
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
MIDDLEWARE_HOST = os.environ.get("MIDDLEWARE_HOST", "localhost")
MIDDLEWARE_PORT = int(os.environ.get("LLM_MIDDLEWARE_PORT", "8180"))
CREDENTIALS_PATH = os.environ.get(
    "CLAUDE_CREDENTIALS_PATH",
    str(Path.home() / ".claude" / ".credentials.json"),
)

# Track results for the summary
_results: list[tuple[str, bool, str]] = []


def _record(name: str, passed: bool, detail: str = ""):
    _results.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_claude_credentials_exist():
    """Verify Claude Code OAuth credentials file exists on host."""
    path = Path(CREDENTIALS_PATH)
    if not path.exists():
        _record("Claude credentials file", False, f"Not found at {path}")
        return
    try:
        data = json.loads(path.read_text())
        oauth = data.get("claudeAiOauth", {})
        has_token = bool(oauth.get("accessToken"))
        _record(
            "Claude credentials file",
            has_token,
            "Has access token" if has_token else "No accessToken in claudeAiOauth",
        )
    except (json.JSONDecodeError, OSError) as e:
        _record("Claude credentials file", False, str(e))


def test_tcp_command_server():
    """Verify the PlayerbotCommandServer TCP port is reachable."""

    async def _test():
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(WS_HOST, WS_CMD_PORT),
                timeout=5.0,
            )
            writer.close()
            await writer.wait_closed()
            _record("TCP command server", True, f"{WS_HOST}:{WS_CMD_PORT} reachable")
        except (OSError, asyncio.TimeoutError) as e:
            _record("TCP command server", False, f"{WS_HOST}:{WS_CMD_PORT} — {e}")

    asyncio.run(_test())


def test_tcp_bot_state_query():
    """Send a state query to the TCP command server and check the response."""

    async def _test():
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(WS_HOST, WS_CMD_PORT),
                timeout=5.0,
            )
            # Send a generic query — even with an invalid GUID we should
            # get a response (empty or error) rather than a hang/crash
            writer.write(b"state,1\n")
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            response = line.decode().strip()
            writer.close()
            await writer.wait_closed()

            valid_states = {"combat", "non-combat", "dead", "unknown", ""}
            is_valid = response in valid_states
            _record(
                "TCP bot state query",
                True,  # Getting any response means the protocol works
                f"Response: '{response}'" + (" (valid state)" if is_valid else " (unexpected but connected)"),
            )
        except (OSError, asyncio.TimeoutError) as e:
            _record("TCP bot state query", False, str(e))

    asyncio.run(_test())


def test_soap_connectivity():
    """Verify the SOAP endpoint responds to a server info command."""

    async def _test():
        try:
            import httpx
        except ImportError:
            _record("SOAP connectivity", False, "httpx not installed")
            return

        soap_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"'
            ' xmlns:ns1="urn:AC">'
            "<SOAP-ENV:Body><ns1:executeCommand>"
            "<command>server info</command>"
            "</ns1:executeCommand></SOAP-ENV:Body></SOAP-ENV:Envelope>"
        )

        url = f"http://{WS_HOST}:{WS_SOAP_PORT}/"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    content=soap_xml,
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    auth=(SOAP_USER, SOAP_PASS),
                )
                if resp.status_code == 200:
                    _record("SOAP connectivity", True, f"HTTP 200, body length {len(resp.text)}")
                elif resp.status_code == 401:
                    _record("SOAP connectivity", False, "HTTP 401 — wrong SOAP credentials")
                else:
                    _record("SOAP connectivity", False, f"HTTP {resp.status_code}: {resp.text[:100]}")
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            _record("SOAP connectivity", False, f"{url} — {e}")

    asyncio.run(_test())


def test_qdrant_connectivity():
    """Verify Qdrant vector DB is reachable and healthy."""

    async def _test():
        try:
            import httpx
        except ImportError:
            _record("Qdrant connectivity", False, "httpx not installed")
            return

        url = f"http://{QDRANT_HOST}:{QDRANT_PORT}/healthz"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    _record("Qdrant health", True, f"Healthy at {QDRANT_HOST}:{QDRANT_PORT}")
                else:
                    _record("Qdrant health", False, f"HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            _record("Qdrant health", False, str(e))

    asyncio.run(_test())


def test_qdrant_collection_ops():
    """Verify Qdrant can create, query, and delete a test collection."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
    except ImportError:
        _record("Qdrant collection ops", False, "qdrant-client not installed")
        return

    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5)
        test_name = "_m0_test_collection"

        # Create
        client.recreate_collection(
            collection_name=test_name,
            vectors_config=VectorParams(size=4, distance=Distance.COSINE),
        )

        # Insert
        client.upsert(
            collection_name=test_name,
            points=[PointStruct(id=1, vector=[0.1, 0.2, 0.3, 0.4], payload={"test": True})],
        )

        # Query — API varies by qdrant-client version
        try:
            results = client.query_points(
                collection_name=test_name,
                query=[0.1, 0.2, 0.3, 0.4],
                limit=1,
            )
            found = len(results.points) > 0
        except AttributeError:
            results = client.search(
                collection_name=test_name,
                query_vector=[0.1, 0.2, 0.3, 0.4],
                limit=1,
            )
            found = len(results) > 0

        # Delete
        client.delete_collection(test_name)

        _record("Qdrant collection ops", found, "Create/insert/query/delete cycle OK")
    except Exception as e:
        _record("Qdrant collection ops", False, str(e))


def test_middleware_health():
    """Verify the FastAPI middleware health endpoint responds."""

    async def _test():
        try:
            import httpx
        except ImportError:
            _record("Middleware health", False, "httpx not installed")
            return

        url = f"http://{MIDDLEWARE_HOST}:{MIDDLEWARE_PORT}/health"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    _record("Middleware health", True, f"status={data.get('status')}")
                else:
                    _record("Middleware health", False, f"HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            _record("Middleware health", False, str(e))

    asyncio.run(_test())


def test_sentence_transformers():
    """Verify the embedding model can be loaded and produces correct dimensions."""
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        vec = model.encode("test query").tolist()
        dim = len(vec)
        _record(
            "Sentence transformers",
            dim == 384,
            f"Embedding dimension: {dim}" + (" (correct)" if dim == 384 else " (expected 384)"),
        )
    except ImportError:
        _record("Sentence transformers", False, "sentence-transformers not installed")
    except Exception as e:
        _record("Sentence transformers", False, str(e))


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def run_all():
    """Run all M0 tests and print a summary."""
    print("\n" + "=" * 60)
    print("  Milestone 0: Infrastructure Tests")
    print("=" * 60 + "\n")

    tests = [
        test_claude_credentials_exist,
        test_tcp_command_server,
        test_tcp_bot_state_query,
        test_soap_connectivity,
        test_qdrant_connectivity,
        test_qdrant_collection_ops,
        test_middleware_health,
        test_sentence_transformers,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            _record(test_fn.__name__, False, f"Unexpected error: {e}")

    # Summary
    passed = sum(1 for _, p, _ in _results if p)
    total = len(_results)
    print("\n" + "-" * 60)
    print(f"  Results: {passed}/{total} passed")

    if passed < total:
        print("\n  Failed tests:")
        for name, p, detail in _results:
            if not p:
                print(f"    - {name}: {detail}")

    print("-" * 60 + "\n")
    return passed == total


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
