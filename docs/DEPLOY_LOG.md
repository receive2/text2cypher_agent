# GCP Neo4j Deployment Log

## Overview
Deploying two benchmark datasets to a single GCP Compute Engine VM:
- **CypherBench** — 7 test graphs loaded from HuggingFace SimpleKG JSON files
- **Mind-the-Query** — 5 graphs restored from Neo4j `.dump` files

## VM Details

| Field | Value |
|-------|-------|
| Instance name | cypherbench-neo4j |
| Zone | us-central1-a |
| Machine type | n2d-highmem-8 (8 vCPU, 64GB RAM) |
| Disk | 100GB |
| External IP | 34.9.85.21 |
| Internal IP | 10.128.0.2 |
| Project | research-infra-494923 |
| Neo4j auth | neo4j / <redacted> (all graphs) |

---

## Part 1: CypherBench

### Target Architecture
- **Image:** `megagonlabs/neo4j-with-loader:2.4` (custom loader)
- **Scope:** 7 test graphs
- **Graph data:** Cloned from HuggingFace with selective `git lfs pull`

---

### Steps

#### Step 1: GCP Authentication & Project Setup
- [x] `gcloud auth login` — geniuswrt@gmail.com
- [x] `gcloud config set project research-infra-494923`
- [x] Enabled Compute Engine API
  ```bash
  gcloud services enable compute.googleapis.com --project=research-infra-494923
  ```

#### Step 2: Create VM
- [x] Created `cypherbench-neo4j` — `e2-standard-4`, `us-central1-a`, 20GB disk
- [x] External IP: `34.69.174.148`
- [x] Status: RUNNING
  ```bash
  gcloud compute instances create cypherbench-neo4j \
    --project=research-infra-494923 --zone=us-central1-a \
    --machine-type=e2-standard-4 --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud --boot-disk-size=20GB \
    --tags=cypherbench --metadata-from-file=startup-script=/tmp/cypherbench-startup.sh
  ```

#### Step 3: Firewall
- [x] Created firewall rule `allow-cypherbench-neo4j` — tcp:15067 ingress (later expanded to 15060–15070)
  ```bash
  gcloud compute firewall-rules create allow-cypherbench-neo4j \
    --project=research-infra-494923 --allow=tcp:15067 \
    --target-tags=cypherbench --direction=INGRESS
  # Expanded to cover all 7 test graph ports
  gcloud compute firewall-rules update allow-cypherbench-neo4j \
    --project=research-infra-494923 --allow=tcp:15060-15070
  ```

#### Step 4: VM Setup
- [x] Installed git, git-lfs, docker (via startup script)
- [x] Cloned cypherbench repo → `/opt/cypherbench`
- [x] Pulled 7 test graph files via `GIT_LFS_SKIP_SMUDGE=1` + selective `git lfs pull`
- [x] Resized disk to 100GB; filesystem auto-expanded
  ```bash
  gcloud compute disks resize cypherbench-neo4j \
    --zone=us-central1-a --project=research-infra-494923 --size=100GB
  ```
- [x] Upgraded machine to `n2d-highmem-8` (64GB RAM) — `n2-highmem-8` unavailable in zone
  ```bash
  gcloud compute instances stop cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923
  gcloud compute instances set-machine-type cypherbench-neo4j \
    --zone=us-central1-a --project=research-infra-494923 --machine-type=n2d-highmem-8
  gcloud compute instances start cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923
  ```
- Note: VM IP changed to `136.112.47.158` after stop/start

#### Step 5: Deploy Graphs
- [x] 7 Docker containers started (image: `megagonlabs/neo4j-with-loader:2.4`)
- [x] All graphs fully imported
  ```bash
  # Run on VM via: gcloud compute ssh cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923
  sudo bash /opt/cypherbench/start_test_graphs.sh
  ```

#### Step 6: Connectivity Test
- [x] All 7 test graphs connected and verified via Python driver and `cypher-shell`
  ```bash
  cypher-shell -a bolt://136.112.47.158:<port> -u neo4j -p <password> "MATCH (n) RETURN count(n);"
  ```

### Deployed Graphs

| Graph | Port | Nodes | Relations | Status |
|-------|------|-------|-----------|--------|
| company | 15062 | 581,306 | 299,581 | **ready** |
| fictional_character | 15063 | 28,915 | 40,548 | **ready** |
| flight_accident | 15064 | 1,683 | 2,212 | **ready** |
| geography | 15065 | 773,489 | 903,794 | **ready** |
| movie | 15066 | 459,393 | 1,892,202 | **ready** |
| nba | 15067 | 4,327 | 18,991 | **ready** |
| politics | 15068 | 885,188 | 1,548,416 | **ready** |

### Systemd Service

Containers managed by `cypherbench.service` — starts all 7 on VM boot, does a fresh import each time.

```bash
sudo systemctl status cypherbench.service
sudo systemctl start cypherbench.service
sudo systemctl stop cypherbench.service
```

Start script: `/opt/cypherbench/start_test_graphs.sh`

---

## Part 2: Mind-the-Query

### Target Architecture
- **Image:** `neo4j:5.20.0` (standard)
- **Scope:** 5 manually validated graphs (bloom, covid, er, healthcare, wwc)
- **Graph data:** Neo4j `.dump` files from `/home/geniuswrt/repo/Mind-the-Query/Datasets/`, uploaded via `gcloud compute scp`
- **Key difference from CypherBench:** Dumps are loaded offline with `neo4j-admin database load` into named Docker volumes, so data persists across container restarts (no crash-loop risk)

### Steps

#### Step 1: Extend Firewall
- [x] Updated `allow-cypherbench-neo4j` rule — expanded from `tcp:15060-15070` to `tcp:15060-15075`
  ```bash
  gcloud compute firewall-rules update allow-cypherbench-neo4j \
    --project=research-infra-494923 --allow=tcp:15060-15075
  ```

#### Step 2: Upload Dump Files
- [x] Created `/opt/mindthequery/dumps/` on VM
- [x] Uploaded 5 dump files via `gcloud compute scp` (total ~4.7MB)
  ```bash
  # Run from /home/geniuswrt/repo/Mind-the-Query/
  gcloud compute scp \
    Datasets/bloom-50.dump Datasets/contact-tracing-50.dump \
    Datasets/entity-resolution-50.dump Datasets/healthcare-analytics-50.dump \
    Datasets/wwc2019-50.dump \
    cypherbench-neo4j:/opt/mindthequery/dumps/ \
    --zone=us-central1-a --project=research-infra-494923
  ```

#### Step 3: Load Dumps into Named Volumes
- [x] Created one Docker named volume per graph (`mtq-<graph>-data`)
- [x] Ran `neo4j:5.20.0` container with `neo4j-admin database load --from-path=/dumps --overwrite-destination=true neo4j` for each
- Note: dump file must be named `neo4j.dump` in the mounted directory (mapped via `-v dump-file:/dumps/neo4j.dump`)
  ```bash
  # Run on VM — example for bloom; repeated for each graph
  docker volume create mtq-bloom-data
  docker run --rm \
    -v /opt/mindthequery/dumps/bloom-50.dump:/dumps/neo4j.dump \
    -v mtq-bloom-data:/data \
    neo4j:5.20.0 neo4j-admin database load --from-path=/dumps --overwrite-destination=true neo4j
  ```

#### Step 4: Start Containers
- [x] 5 containers started with named volumes — no import on startup, instant boot
  ```bash
  # Run on VM
  sudo bash /opt/mindthequery/start_mtq_graphs.sh
  ```

#### Step 5: Connectivity Test
- [x] All 5 graphs verified via `cypher-shell`
  ```bash
  cypher-shell -a bolt://136.112.47.158:<port> -u neo4j -p <password> "MATCH (n) RETURN count(n);"
  ```

### Deployed Graphs

| Graph | Port | Source Dump | Nodes | Status |
|-------|------|-------------|-------|--------|
| bloom | 15071 | bloom-50.dump | 30,960 | **ready** |
| covid | 15072 | contact-tracing-50.dump | 5,615 | **ready** |
| er | 15073 | entity-resolution-50.dump | 1,237 | **ready** |
| healthcare | 15074 | healthcare-analytics-50.dump | 11,381 | **ready** |
| wwc | 15075 | wwc2019-50.dump | 2,486 | **ready** |

### Systemd Service

Containers managed by `mindthequery.service` — starts after `cypherbench.service` on VM boot. Data lives in named volumes so no re-import on restart.

```bash
sudo systemctl status mindthequery.service
sudo systemctl start mindthequery.service
sudo systemctl stop mindthequery.service
```

Start script: `/opt/mindthequery/start_mtq_graphs.sh`

---

## Part 3: ZOGRASCOPE

### Target Architecture
- **Image:** `neo4j:5.20.0` (standard)
- **Scope:** 1 graph — `pole-50` (policing/crime)
- **Graph data:** `pole-50.dump` from `/home/geniuswrt/repo/ZOGRASCOPE/graph/`, uploaded via `gcloud compute scp`
- **Same approach as MTQ:** dump loaded offline into a named Docker volume

### Steps

#### Step 1: Extend Firewall
- [x] Updated `allow-cypherbench-neo4j` rule — expanded to `tcp:15060-15076`
  ```bash
  gcloud compute firewall-rules update allow-cypherbench-neo4j \
    --project=research-infra-494923 --allow=tcp:15060-15076
  ```

#### Step 2: Upload & Load Dump
- [x] Uploaded `pole-50.dump` to `/opt/mindthequery/dumps/` on VM
  ```bash
  gcloud compute scp /home/geniuswrt/repo/ZOGRASCOPE/graph/pole-50.dump \
    cypherbench-neo4j:/opt/mindthequery/dumps/ \
    --zone=us-central1-a --project=research-infra-494923
  ```
- [x] Created named volume `zograscope-pole-data` and loaded dump — 112 files, 21.36MiB processed
  ```bash
  # Run on VM
  docker volume create zograscope-pole-data
  docker run --rm \
    -v /opt/mindthequery/dumps/pole-50.dump:/dumps/neo4j.dump \
    -v zograscope-pole-data:/data \
    neo4j:5.20.0 neo4j-admin database load --from-path=/dumps --overwrite-destination=true neo4j
  ```

#### Step 3: Start Container
- [x] Container `zograscope-pole` started on port 15076
  ```bash
  # Run on VM
  sudo bash /opt/zograscope/start_zograscope_graphs.sh
  ```

#### Step 4: Connectivity Test
- [x] 61,521 nodes confirmed via `cypher-shell`
  ```bash
  cypher-shell -a bolt://136.112.47.158:15076 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
  ```

### Deployed Graphs

| Graph | Port | Nodes | Status |
|-------|------|-------|--------|
| pole | 15076 | 61,521 | **ready** |

**Node labels:** `Area`, `Crime`, `Email`, `Location`, `Object`, `Officer`, `Person`, `Phone`, `PhoneCall`, `PostCode`, `Vehicle`

**Rel types:** `CALLED`, `CALLER`, `CURRENT_ADDRESS`, `FAMILY_REL`, `HAS_EMAIL`, `HAS_PHONE`, `HAS_POSTCODE`, `INVESTIGATED_BY`, `INVOLVED_IN`, `KNOWS`, `KNOWS_LW`, `KNOWS_PHONE`, `KNOWS_SN`, `LOCATION_IN_AREA`, `OCCURRED_AT`, `PARTY_TO`, `POSTCODE_IN_AREA`

### Systemd Service

Container managed by `zograscope.service` — starts after `mindthequery.service` on VM boot.

```bash
sudo systemctl status zograscope.service
sudo systemctl start zograscope.service
sudo systemctl stop zograscope.service
```

Start script: `/opt/zograscope/start_zograscope_graphs.sh`

---

## How to Connect

```python
from neo4j import GraphDatabase
# CypherBench example
driver = GraphDatabase.driver("bolt://136.112.47.158:15067", auth=("neo4j", "<password>"))
# Mind-the-Query example
driver = GraphDatabase.driver("bolt://136.112.47.158:15071", auth=("neo4j", "<password>"))
```

```bash
# Via cypher-shell
cypher-shell -a bolt://136.112.47.158:<port> -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```

---

## Part 4: APOC Installation

### Target
- **Scope:** All 13 Neo4j containers
- **APOC version:** 5.20.0 (matches Neo4j 5.20.0)
- **Discovery:** CypherBench already had APOC in `megagonlabs/neo4j-with-loader:2.4`; MTQ and ZOGRASCOPE needed it added

### Steps

#### Step 1: Download APOC JAR
- [x] Downloaded `apoc-5.20.0-core.jar` to `/opt/apoc/` on VM
  ```bash
  sudo mkdir -p /opt/apoc
  sudo curl -L -o /opt/apoc/apoc-5.20.0-core.jar \
    https://github.com/neo4j/apoc/releases/download/5.20.0/apoc-5.20.0-core.jar
  ```

#### Step 2: Patch Start Scripts
- [x] `/opt/mindthequery/start_mtq_graphs.sh` — added plugin volume mount and unrestricted env var to each `docker run` call
- [x] `/opt/zograscope/start_zograscope_graphs.sh` — same
- Each `docker run` now includes:
  ```
  -v /opt/apoc/apoc-5.20.0-core.jar:/plugins/apoc-5.20.0-core.jar
  -e NEO4J_dbms_security_procedures_unrestricted='apoc.*'
  ```

#### Step 3: Restart Services
- [x] `sudo systemctl restart mindthequery.service zograscope.service`

#### Step 4: Verification
- [x] All 6 MTQ + ZOGRASCOPE containers confirmed: `apoc.version()` → `"5.20.0"`, 192 procedures loaded
- [x] All 7 CypherBench containers confirmed: APOC already present in image, same version and count

### Result

| Suite | Containers | APOC source |
|-------|-----------|-------------|
| CypherBench (ports 15062–15068) | 7 | Bundled in `megagonlabs/neo4j-with-loader:2.4` |
| Mind-the-Query (ports 15071–15075) | 5 | `/opt/apoc/apoc-5.20.0-core.jar` mounted at startup |
| ZOGRASCOPE (port 15076) | 1 | `/opt/apoc/apoc-5.20.0-core.jar` mounted at startup |

Install script: `scripts/install_apoc.sh` (in this repo)

---

## Bugs & Fixes

### Bug 1: `$HOME not set` in git-lfs during startup script
- **Cause:** The GCP startup script runs as root without a HOME env var; `git lfs install` failed.
- **Fix:** Set `export HOME=/root` before running git-lfs commands. Ran remaining steps manually via SSH.

### Bug 2: `n2-highmem-8` zone capacity exhausted
- **Cause:** `ZONE_RESOURCE_POOL_EXHAUSTED` — no `n2-highmem-8` VMs available in `us-central1-a`.
- **Fix:** Used `n2d-highmem-8` (AMD equivalent, same 64GB RAM) instead. VM started successfully.

### Bug 3: External IP changed after VM stop/start
- **Cause:** GCP assigns ephemeral IPs; stopping the VM for a machine type change released the original IP (`34.69.174.148`), new IP is `136.112.47.158`.
- **Fix:** Updated all references to use the new IP. Could be avoided in future by reserving a static IP.

### Bug 4: NBA container in crash loop (61 restarts)
- **Cause:** The `megagonlabs/neo4j-with-loader:2.4` entrypoint runs `loader.py` on every start. The loader raises `ValueError: Database is not empty` when data already exists and `--overwrite` is not passed. With `set -e` in the entrypoint, this exits the container. `--restart unless-stopped` then causes an infinite loop. Only affects containers that restart (e.g. after VM reboot) — large graphs aren't affected during normal operation because their import takes long enough that we don't notice.
- **Fix:** Removed `--restart unless-stopped` from all containers. Created a systemd service (`/etc/systemd/system/cypherbench.service`) that starts all containers from scratch on VM boot. Each boot does one fresh clean import.

---

## Commands Log

```bash
# 2026-04-30 — CypherBench
gcloud services enable compute.googleapis.com --project=research-infra-494923
gcloud compute firewall-rules create allow-cypherbench-neo4j --project=research-infra-494923 --allow=tcp:15067 --target-tags=cypherbench --direction=INGRESS
gcloud compute instances create cypherbench-neo4j --project=research-infra-494923 --zone=us-central1-a --machine-type=e2-standard-4 --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud --boot-disk-size=20GB --tags=cypherbench --metadata-from-file=startup-script=/tmp/cypherbench-startup.sh
# Upgraded disk to 100GB (online resize)
gcloud compute disks resize cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923 --size=100GB
# Updated firewall to cover all test graph ports
gcloud compute firewall-rules update allow-cypherbench-neo4j --project=research-infra-494923 --allow=tcp:15060-15070
# Stopped VM, changed machine type to n2d-highmem-8, restarted
gcloud compute instances stop cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923
gcloud compute instances set-machine-type cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923 --machine-type=n2d-highmem-8
gcloud compute instances start cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923

# 2026-05-01 — Mind-the-Query
# Extend firewall to cover MTQ ports
gcloud compute firewall-rules update allow-cypherbench-neo4j --project=research-infra-494923 --allow=tcp:15060-15075
# Upload dump files
gcloud compute scp Datasets/bloom-50.dump Datasets/contact-tracing-50.dump Datasets/entity-resolution-50.dump Datasets/healthcare-analytics-50.dump Datasets/wwc2019-50.dump cypherbench-neo4j:/tmp/ --zone=us-central1-a --project=research-infra-494923
# Load each dump into a named volume (example for bloom; repeated for each graph)
docker volume create mtq-bloom-data
docker run --rm -v /opt/mindthequery/dumps/bloom-50.dump:/dumps/neo4j.dump -v mtq-bloom-data:/data neo4j:5.20.0 neo4j-admin database load --from-path=/dumps --overwrite-destination=true neo4j
# Start container
docker run -d --name mtq-bloom -p 15071:7687 -v mtq-bloom-data:/data -e NEO4J_AUTH='neo4j/<password>' neo4j:5.20.0

# 2026-05-01 — ZOGRASCOPE
# Extend firewall to port 15076
gcloud compute firewall-rules update allow-cypherbench-neo4j --project=research-infra-494923 --allow=tcp:15060-15076
# Upload dump
gcloud compute scp /home/geniuswrt/repo/ZOGRASCOPE/graph/pole-50.dump cypherbench-neo4j:/tmp/ --zone=us-central1-a --project=research-infra-494923
# Load into named volume
docker volume create zograscope-pole-data
docker run --rm -v /opt/mindthequery/dumps/pole-50.dump:/dumps/neo4j.dump -v zograscope-pole-data:/data neo4j:5.20.0 neo4j-admin database load --from-path=/dumps --overwrite-destination=true neo4j
# Start container
docker run -d --name zograscope-pole -p 15076:7687 -v zograscope-pole-data:/data -e NEO4J_AUTH='neo4j/<password>' neo4j:5.20.0
```
