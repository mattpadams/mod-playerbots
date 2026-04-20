"""Middleware-owned persistence layer (acore_llmbots database).

Separate from ``core/db_client.py`` which reads from game-owned
databases (acore_auth, acore_characters, acore_playerbots). The ``db``
package owns all writes and lives entirely in ``acore_llmbots``.
"""
