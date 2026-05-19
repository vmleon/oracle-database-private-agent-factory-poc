#!/bin/bash
# Startup hook: switch the CDB, PDB$SEED, and FREEPDB1 to
# MAX_STRING_SIZE=EXTENDED and leave all PDBs OPEN with saved states.
# Required by Private Agent Factory (PAF §5.1). Mounted under
# /opt/oracle/scripts/startup so it runs every boot — the script is
# idempotent: opens PDBs if closed, and skips the upgrade dance when
# max_string_size is already EXTENDED. scripts/setup is skipped on
# Oracle Free 26ai because the image ships with a prebuilt database.
#
# The migration is three-phase: CDB first, then each PDB after the CDB
# has restarted with the new MAX_STRING_SIZE active (the SCOPE=SPFILE
# setting isn't live in the running instance until that second startup).
# utl32k must run in every container — CDB$ROOT, PDB$SEED, and FREEPDB1.
# Skipping any of them leaves the PDB stuck in MOUNTED with ORA-14694
# on subsequent OPEN, which also breaks the image's checkDBStatus.sh.
set -euo pipefail

echo "[init] Ensuring all PDBs are open + state saved..."
sqlplus -s -L / as sysdba <<'SQL'
WHENEVER SQLERROR CONTINUE;
ALTER PLUGGABLE DATABASE "PDB$SEED" OPEN READ ONLY;
ALTER PLUGGABLE DATABASE FREEPDB1 OPEN;
ALTER PLUGGABLE DATABASE ALL SAVE STATE;
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

echo "[init] Phase 2a: PDB\$SEED upgrade..."
sqlplus -s -L / as sysdba <<'SQL'
WHENEVER SQLERROR EXIT SQL.SQLCODE;
ALTER PLUGGABLE DATABASE "PDB$SEED" OPEN UPGRADE;
ALTER SESSION SET CONTAINER="PDB$SEED";
@?/rdbms/admin/utl32k.sql
ALTER SESSION SET CONTAINER=CDB$ROOT;
ALTER PLUGGABLE DATABASE "PDB$SEED" CLOSE IMMEDIATE;
ALTER PLUGGABLE DATABASE "PDB$SEED" OPEN READ ONLY;
ALTER PLUGGABLE DATABASE "PDB$SEED" SAVE STATE;
EXIT;
SQL

echo "[init] Phase 2b: FREEPDB1 upgrade..."
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

echo "[init] max_string_size is now EXTENDED and all PDBs are OPEN."
