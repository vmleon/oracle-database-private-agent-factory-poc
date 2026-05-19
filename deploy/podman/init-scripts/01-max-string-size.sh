#!/bin/bash
# Startup hook: switch the CDB + FREEPDB1 to MAX_STRING_SIZE=EXTENDED and
# ensure FREEPDB1 is OPEN with a saved state.
# Required by Private Agent Factory (PAF §5.1). Mounted under
# /opt/oracle/scripts/startup so it runs every boot — the script is
# idempotent: opens the PDB if closed, and skips the upgrade dance when
# max_string_size is already EXTENDED. scripts/setup is skipped on
# Oracle Free 26ai because the image ships with a prebuilt database.
#
# The migration is two-phase: CDB first, then PDB after CDB has restarted
# with the new MAX_STRING_SIZE active (the SCOPE=SPFILE setting isn't
# live in the running instance until that second startup, so utl32k in
# the PDB has to run afterwards).
set -euo pipefail

echo "[init] Ensuring FREEPDB1 is open + state saved..."
sqlplus -s -L / as sysdba <<'SQL'
WHENEVER SQLERROR CONTINUE;
ALTER PLUGGABLE DATABASE FREEPDB1 OPEN;
ALTER PLUGGABLE DATABASE FREEPDB1 SAVE STATE;
EXIT;
SQL

current=$(sqlplus -s -L / as sysdba <<'SQL' | tr -d '[:space:]'
SET HEAD OFF FEEDBACK OFF PAGES 0 ECHO OFF
SELECT value FROM v$parameter WHERE name='max_string_size';
EXIT;
SQL
)

if [ "$current" = "EXTENDED" ]; then
  echo "[init] max_string_size already EXTENDED — done."
  exit 0
fi

echo "[init] Phase 1: CDB upgrade to MAX_STRING_SIZE=EXTENDED..."
sqlplus -s -L / as sysdba <<'SQL'
WHENEVER SQLERROR EXIT SQL.SQLCODE;
SHUTDOWN IMMEDIATE;
STARTUP UPGRADE;
ALTER SYSTEM SET MAX_STRING_SIZE=EXTENDED SCOPE=SPFILE;
@?/rdbms/admin/utl32k.sql
SHUTDOWN IMMEDIATE;
STARTUP;
EXIT;
SQL

echo "[init] Phase 2: FREEPDB1 upgrade..."
sqlplus -s -L / as sysdba <<'SQL'
WHENEVER SQLERROR EXIT SQL.SQLCODE;
ALTER PLUGGABLE DATABASE FREEPDB1 OPEN UPGRADE;
ALTER SESSION SET CONTAINER=FREEPDB1;
@?/rdbms/admin/utl32k.sql
ALTER SESSION SET CONTAINER=CDB$ROOT;
ALTER PLUGGABLE DATABASE FREEPDB1 CLOSE IMMEDIATE;
ALTER PLUGGABLE DATABASE FREEPDB1 OPEN;
ALTER PLUGGABLE DATABASE FREEPDB1 SAVE STATE;
EXIT;
SQL

echo "[init] max_string_size is now EXTENDED and FREEPDB1 is OPEN."
