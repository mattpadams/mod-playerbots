"""Repository layer for acore_llmbots.

Each module exports a class whose methods take an ``AsyncSession`` and
perform a single unit of work. Composition and transaction scope are
the caller's responsibility (typically the service layer).
"""
