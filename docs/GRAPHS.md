# Deployed Neo4j Graphs

All graphs run on VM `34.9.85.21` (GCP, `us-central1-a`).
**Auth:** `neo4j` / `<password>` (all graphs)

**APOC:** All 13 graphs have APOC 5.20.0 installed (192 procedures).
- CypherBench — bundled in the `megagonlabs/neo4j-with-loader:2.4` image
- Mind-the-Query + ZOGRASCOPE — JAR mounted from `/opt/apoc/apoc-5.20.0-core.jar` on the VM

---

## Quick Reference

| Graph | Dataset | Port | Nodes | Relations |
|-------|---------|------|-------|-----------|
| company | CypherBench | 15062 | 581,306 | 299,581 |
| fictional_character | CypherBench | 15063 | 28,915 | 40,548 |
| flight_accident | CypherBench | 15064 | 1,683 | 2,212 |
| geography | CypherBench | 15065 | 773,489 | 903,794 |
| movie | CypherBench | 15066 | 459,393 | 1,892,202 |
| nba | CypherBench | 15067 | 4,327 | 18,991 |
| politics | CypherBench | 15068 | 885,188 | 1,548,416 |
| bloom | Mind-the-Query | 15071 | 30,960 | — |
| covid | Mind-the-Query | 15072 | 5,615 | — |
| er | Mind-the-Query | 15073 | 1,237 | — |
| healthcare | Mind-the-Query | 15074 | 11,381 | — |
| wwc | Mind-the-Query | 15075 | 2,486 | — |
| pole | ZOGRASCOPE | 15076 | 61,521 | — |

---

## CypherBench Graphs

### company — port 15062
- **Node labels:** `Company`, `Country`, `Industry`, `Person`
- **Rel types:** `basedIn`, `foundedBy`, `hasBoardMember`, `hasCEO`, `operatesIn`, `subsidiaryOf`

```bash
cypher-shell -a bolt://34.9.85.21:15062 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15062", auth=("neo4j", "<password>"))
```

---

### fictional_character — port 15063
- **Node labels:** `Character`, `FictionalUniverse`, `Location`, `Organization`
- **Rel types:** `basedIn`, `bornIn`, `diedIn`, `fromUniverse`, `hasFather`, `hasMother`, `hasSpouse`, `hasStudent`, `killedBy`, `memberOf`

```bash
cypher-shell -a bolt://34.9.85.21:15063 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15063", auth=("neo4j", "<password>"))
```

---

### flight_accident — port 15064
- **Node labels:** `AircraftManufacturer`, `AircraftModel`, `Airport`, `FlightAccident`, `Operator`
- **Rel types:** `departsFrom`, `destinedFor`, `involves`, `manufacturedBy`, `operatedBy`

```bash
cypher-shell -a bolt://34.9.85.21:15064 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15064", auth=("neo4j", "<password>"))
```

---

### geography — port 15065
- **Node labels:** `Continent`, `Country`, `DrainageBasin`, `Lake`, `Mountain`, `MountainRange`, `Ocean`, `River`
- **Rel types:** `flowsInto`, `flowsThrough`, `locatedIn`, `partOf`

```bash
cypher-shell -a bolt://34.9.85.21:15065 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15065", auth=("neo4j", "<password>"))
```

---

### movie — port 15066
- **Node labels:** `Award`, `Country`, `FilmSeries`, `Genre`, `Movie`, `Person`, `ProductionCompany`
- **Rel types:** `directedBy`, `hasCastMember`, `hasGenre`, `originatesFrom`, `partOfSeries`, `producedBy`, `receivesAward`, `releasedIn`, `writtenBy`

```bash
cypher-shell -a bolt://34.9.85.21:15066 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15066", auth=("neo4j", "<password>"))
```

---

### nba — port 15067
- **Node labels:** `Award`, `Conference`, `Division`, `Player`, `Position`, `Team`, `Venue`
- **Rel types:** `draftedBy`, `hasHomeVenue`, `partOfConference`, `partOfDivision`, `playsFor`, `playsPosition`, `receivesAward`

```bash
cypher-shell -a bolt://34.9.85.21:15067 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15067", auth=("neo4j", "<password>"))
```

---

### politics — port 15068
- **Node labels:** `Country`, `GovernmentOrganization`, `InternationalOrganization`, `PoliticalParty`, `Politician`, `Position`
- **Rel types:** `belongsTo`, `foundedBy`, `hasDiplomaticRelationWith`, `hasHeadOfGovernment`, `hasHeadOfState`, `headedBy`, `holdsPosition`, `leads`, `memberOf`, `operatesIn`

```bash
cypher-shell -a bolt://34.9.85.21:15068 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15068", auth=("neo4j", "<password>"))
```

---

## Mind-the-Query Graphs

### bloom — port 15071
- **Domain:** Fraud detection (financial graph)
- **Node labels:** `AccountHolder`, `Address`, `BankAccount`, `BankCard`, `CreditCard`, `DeliveryAddress`, `FinancialInstitute`, `Flagged`, `IP`, `Login`, `MoneyTransfer`, `PhoneNumber`, `Purchase`, `Shop`, `SSN`, `State`, `UnsecuredLoan`
- **Rel types:** `DELIVERED_AT`, `FOR_SHOP`, `FROM`, `FROM_IP`, `HAS_ADDRESS`, `HAS_BANKACCOUNT`, `HAS_CREDITCARD`, `HAS_PHONENUMBER`, `HAS_SSN`, `HAS_UNSECUREDLOAN`, `LOCATED_IN`, `SEND`, `WITH`, `WITH_CARD`, `WITH_LOGIN`

```bash
cypher-shell -a bolt://34.9.85.21:15071 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15071", auth=("neo4j", "<password>"))
```

---

### covid — port 15072
- **Domain:** Contact tracing
- **Node labels:** `Continent`, `Country`, `Person`, `Place`, `Region`, `Visit`
- **Rel types:** `LOCATED_AT`, `PART_OF`, `PERFORMS_VISIT`, `VISITS`

```bash
cypher-shell -a bolt://34.9.85.21:15072 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15072", auth=("neo4j", "<password>"))
```

---

### er — port 15073
- **Domain:** Entity resolution (movies/users)
- **Node labels:** `Genre`, `IpAddress`, `Movie`, `User`
- **Rel types:** `HAS`, `USES`, `WATCHED`

```bash
cypher-shell -a bolt://34.9.85.21:15073 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15073", auth=("neo4j", "<password>"))
```

---

### healthcare — port 15074
- **Domain:** Adverse drug reactions
- **Node labels:** `AgeGroup`, `Case`, `Drug`, `Manufacturer`, `Outcome`, `Reaction`, `ReportSource`, `Therapy`
- **Rel types:** `FALLS_UNDER`, `HAS_REACTION`, `IS_CONCOMITANT`, `IS_INTERACTING`, `IS_PRIMARY_SUSPECT`, `IS_SECONDARY_SUSPECT`, `PRESCRIBED`, `RECEIVED`, `REGISTERED`, `REPORTED_BY`, `RESULTED_IN`

```bash
cypher-shell -a bolt://34.9.85.21:15074 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15074", auth=("neo4j", "<password>"))
```

---

### wwc — port 15075
- **Domain:** 2019 Women's World Cup
- **Node labels:** `Match`, `Person`, `Squad`, `Team`, `Tournament`
- **Rel types:** `COACH_FOR`, `FOR`, `IN_SQUAD`, `IN_TOURNAMENT`, `NAMED`, `PARTICIPATED_IN`, `PLAYED_IN`, `REPRESENTS`, `SCORED_GOAL`

```bash
cypher-shell -a bolt://34.9.85.21:15075 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15075", auth=("neo4j", "<password>"))
```

---

## ZOGRASCOPE Graphs

### pole — port 15076
- **Domain:** Policing / crime investigation
- **Node labels:** `Area`, `Crime`, `Email`, `Location`, `Object`, `Officer`, `Person`, `Phone`, `PhoneCall`, `PostCode`, `Vehicle`
- **Rel types:** `CALLED`, `CALLER`, `CURRENT_ADDRESS`, `FAMILY_REL`, `HAS_EMAIL`, `HAS_PHONE`, `HAS_POSTCODE`, `INVESTIGATED_BY`, `INVOLVED_IN`, `KNOWS`, `KNOWS_LW`, `KNOWS_PHONE`, `KNOWS_SN`, `LOCATION_IN_AREA`, `OCCURRED_AT`, `PARTY_TO`, `POSTCODE_IN_AREA`

```bash
cypher-shell -a bolt://34.9.85.21:15076 -u neo4j -p <password> "MATCH (n) RETURN count(n);"
```
```python
driver = GraphDatabase.driver("bolt://34.9.85.21:15076", auth=("neo4j", "<password>"))
```

---

## Python Boilerplate

```python
from neo4j import GraphDatabase

GRAPHS = {
    # CypherBench
    "company":              "bolt://34.9.85.21:15062",
    "fictional_character":  "bolt://34.9.85.21:15063",
    "flight_accident":      "bolt://34.9.85.21:15064",
    "geography":            "bolt://34.9.85.21:15065",
    "movie":                "bolt://34.9.85.21:15066",
    "nba":                  "bolt://34.9.85.21:15067",
    "politics":             "bolt://34.9.85.21:15068",
    # Mind-the-Query
    "bloom":                "bolt://34.9.85.21:15071",
    "covid":                "bolt://34.9.85.21:15072",
    "er":                   "bolt://34.9.85.21:15073",
    "healthcare":           "bolt://34.9.85.21:15074",
    "wwc":                  "bolt://34.9.85.21:15075",
    # ZOGRASCOPE
    "pole":                 "bolt://34.9.85.21:15076",
}

def get_driver(graph_name):
    return GraphDatabase.driver(GRAPHS[graph_name], auth=("neo4j", "<password>"))
```
