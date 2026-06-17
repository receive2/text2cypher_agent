#!/bin/bash
# Install APOC 5.20.0 for Mind-the-Query and ZOGRASCOPE Neo4j containers.
# Run on the GCP VM as root (or via sudo).
set -e

APOC_VERSION="5.20.0"
APOC_JAR="apoc-${APOC_VERSION}-core.jar"
APOC_DIR="/opt/apoc"
APOC_URL="https://github.com/neo4j/apoc/releases/download/${APOC_VERSION}/${APOC_JAR}"

# ── 1. Download APOC JAR ──────────────────────────────────────────────────────
mkdir -p "$APOC_DIR"
if [ ! -f "$APOC_DIR/$APOC_JAR" ]; then
  echo "Downloading APOC ${APOC_VERSION}..."
  curl -L --fail -o "$APOC_DIR/$APOC_JAR" "$APOC_URL"
  echo "Downloaded: $APOC_DIR/$APOC_JAR"
else
  echo "APOC JAR already present: $APOC_DIR/$APOC_JAR"
fi

# ── 2. Patch start scripts ────────────────────────────────────────────────────
MTQ_SCRIPT="/opt/mindthequery/start_mtq_graphs.sh"
ZGS_SCRIPT="/opt/zograscope/start_zograscope_graphs.sh"

patch_script() {
  local script="$1"
  if grep -q "apoc" "$script"; then
    echo "APOC already configured in $script — skipping patch."
    return
  fi

  # Back up original
  cp "$script" "${script}.bak"

  # Insert plugin volume mount and unrestricted-procedures env var
  # before the closing `neo4j:5.20.0` image reference.
  sed -i \
    "s|    neo4j:5.20.0|    -v ${APOC_DIR}/${APOC_JAR}:/plugins/${APOC_JAR} \\\\\n    -e NEO4J_dbms_security_procedures_unrestricted='apoc.*' \\\\\n    -e NEO4J_dbms_security_functions_unrestricted='apoc.*' \\\\\n    neo4j:5.20.0|g" \
    "$script"

  echo "Patched: $script  (backup → ${script}.bak)"
}

patch_script "$MTQ_SCRIPT"
patch_script "$ZGS_SCRIPT"

# ── 3. Restart services ───────────────────────────────────────────────────────
echo "Restarting mindthequery.service..."
systemctl restart mindthequery.service

echo "Restarting zograscope.service..."
systemctl restart zograscope.service

# ── 4. Verify APOC is loaded ──────────────────────────────────────────────────
echo ""
echo "Waiting 20s for containers to start..."
sleep 20

NEO4J_PASS="37fhWZ746X9QCwxPUoU5"

for port in 15071 15072 15073 15074 15075 15076; do
  result=$(cypher-shell -a "bolt://localhost:${port}" \
    -u neo4j -p "$NEO4J_PASS" \
    "RETURN apoc.version() AS apoc_version" 2>&1 | tail -1)
  echo "Port ${port}: ${result}"
done
