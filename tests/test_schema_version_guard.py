"""Tripwire: jp-core schema DDL must not change without bumping the version.

The runtime schema guard (base.py) raises SchemaVersionError when a DB's stored
DDL checksum differs from the code's. If someone edits CORE_DDL but leaves
CORE_SCHEMA_VERSION unchanged, there is no migration for "same version, new DDL",
so every already-migrated jp-core-v8 database (incl. the ~4GB production DB) would
fail to open — a full outage with no automatic recovery.

This test fails fast in CI on any CORE_DDL change, forcing the author to either
revert, or bump CORE_SCHEMA_VERSION + add a CORE_MIGRATIONS entry, and then update
the pinned checksum below.
"""

from app.repositories.base import schema_checksum
from app.repositories.core_schema import (
    CORE_DDL,
    CORE_MIGRATIONS,
    CORE_SCHEMA_VERSION,
)

# Bump these together whenever CORE_DDL changes (and add the matching migration).
EXPECTED_VERSION = "jp-core-v9"
EXPECTED_CHECKSUM = "011dd150b68b94aeffa3af8d0e124d09cfee23e796437a64b15e77b6ecf592e8"


def test_core_ddl_change_requires_version_bump():
    assert CORE_SCHEMA_VERSION == EXPECTED_VERSION, (
        "CORE_SCHEMA_VERSION changed — update EXPECTED_VERSION/EXPECTED_CHECKSUM here "
        "and ensure a CORE_MIGRATIONS entry migrates the previous version to it."
    )
    assert schema_checksum(CORE_DDL) == EXPECTED_CHECKSUM, (
        "CORE_DDL changed without bumping CORE_SCHEMA_VERSION. Editing the DDL text "
        "while the version string stays the same bricks every already-migrated "
        "jp-core DB (checksum mismatch -> SchemaVersionError, no recovery). Bump "
        "CORE_SCHEMA_VERSION, add a CORE_MIGRATIONS entry that reaches the new "
        "version, then update EXPECTED_VERSION/EXPECTED_CHECKSUM."
    )


def test_migrations_reach_the_current_version():
    targets = {target for (_ddl, target) in CORE_MIGRATIONS.values()}
    assert CORE_SCHEMA_VERSION in targets, (
        "No CORE_MIGRATIONS entry migrates a prior version to the current "
        f"{CORE_SCHEMA_VERSION}; existing v-N DBs could not be upgraded."
    )
