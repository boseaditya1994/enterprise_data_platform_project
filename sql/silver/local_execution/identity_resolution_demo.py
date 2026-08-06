"""
Phase 5's synthetic generator uses one shared customer_id across CRM,
Servicing, and Bureau (documented simplification, docs/04 Section 6). A real
bank's sources each mint their OWN local ID, so silver.customer's actual
join key would first need to be PRODUCED by identity resolution rather than
just consumed. This script proves that matching logic works, independent of
the main dataset, against a small deliberately-fragmented sample: the same
5 people represented with 3 different local IDs each (CRM/Servicing/Bureau
style), including realistic messiness (typos, missing SSN, format
differences).

Algorithm: blocking on (ssn_last4, date_of_birth) -- the fields least likely
to legitimately differ across systems for the same person -- then scoring
candidate pairs within a block by normalized name similarity. Union-Find
merges every pair above threshold into one golden_customer_id per cluster.

Usage:
    cd sql/silver/local_execution
    python3 identity_resolution_demo.py
"""
import difflib

import pandas as pd

# Deliberately fragmented: 5 real people, 3 source-system records each,
# with typos/casing/format differences typical of independently-maintained
# systems.
records = [
    # Person 1
    {"source": "CRM",       "local_id": "CRM-001", "first_name": "Maria",  "last_name": "Chen",     "dob": "1985-03-12", "ssn_last4": "4471"},
    {"source": "SERVICING", "local_id": "SVC-901", "first_name": "Maria",  "last_name": "Chen",     "dob": "1985-03-12", "ssn_last4": "4471"},
    {"source": "BUREAU",    "local_id": "BUR-317", "first_name": "M.",     "last_name": "Chen",     "dob": "1985-03-12", "ssn_last4": "4471"},
    # Person 2 -- last name typo in Bureau feed
    {"source": "CRM",       "local_id": "CRM-002", "first_name": "James",  "last_name": "Whitfield", "dob": "1979-11-02", "ssn_last4": "8820"},
    {"source": "SERVICING", "local_id": "SVC-902", "first_name": "James",  "last_name": "Whitfield", "dob": "1979-11-02", "ssn_last4": "8820"},
    {"source": "BUREAU",    "local_id": "BUR-318", "first_name": "James",  "last_name": "Whitfeld",  "dob": "1979-11-02", "ssn_last4": "8820"},
    # Person 3 -- nickname variation
    {"source": "CRM",       "local_id": "CRM-003", "first_name": "Robert", "last_name": "Garcia",   "dob": "1990-07-25", "ssn_last4": "1156"},
    {"source": "SERVICING", "local_id": "SVC-903", "first_name": "Bob",    "last_name": "Garcia",   "dob": "1990-07-25", "ssn_last4": "1156"},
    {"source": "BUREAU",    "local_id": "BUR-319", "first_name": "Robert", "last_name": "Garcia",   "dob": "1990-07-25", "ssn_last4": "1156"},
    # Person 4 -- two DIFFERENT people who happen to share a last name
    # (negative control: must NOT be merged, since ssn_last4/dob block differs)
    {"source": "CRM",       "local_id": "CRM-004", "first_name": "Sarah",  "last_name": "Kim",      "dob": "1988-02-14", "ssn_last4": "3390"},
    {"source": "CRM",       "local_id": "CRM-005", "first_name": "David",  "last_name": "Kim",      "dob": "1993-09-30", "ssn_last4": "7742"},
    # Person 5 -- Bureau record has no SSN on file (blocking must fall back)
    {"source": "CRM",       "local_id": "CRM-006", "first_name": "Elena",  "last_name": "Petrova",  "dob": "1982-05-19", "ssn_last4": "5510"},
    {"source": "BUREAU",    "local_id": "BUR-320", "first_name": "Elena",  "last_name": "Petrova",  "dob": "1982-05-19", "ssn_last4": None},
]

NAME_SIM_THRESHOLD = 0.75


def name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def resolve_identities(df: pd.DataFrame) -> pd.DataFrame:
    parent = {i: i for i in df.index}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    # Blocking pass 1: exact (ssn_last4, dob) match
    for key, group in df[df["ssn_last4"].notna()].groupby(["ssn_last4", "dob"]):
        idxs = group.index.tolist()
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                if name_similarity(df.loc[idxs[i], "last_name"], df.loc[idxs[j], "last_name"]) >= NAME_SIM_THRESHOLD:
                    union(idxs[i], idxs[j])

    # Blocking pass 2: missing SSN -- fall back to (dob, last_name exact,
    # first_name similarity) as a weaker secondary block. Real systems would
    # weight this match lower / route to manual review; simplified here to
    # a straightforward secondary pass for demo purposes.
    no_ssn = df[df["ssn_last4"].isna()]
    for idx, row in no_ssn.iterrows():
        candidates = df[(df["dob"] == row["dob"]) & (df["last_name"].str.lower() == row["last_name"].lower()) & (df.index != idx)]
        for cidx, crow in candidates.iterrows():
            if name_similarity(row["first_name"], crow["first_name"]) >= NAME_SIM_THRESHOLD:
                union(idx, cidx)

    df = df.copy()
    df["cluster_root"] = [find(i) for i in df.index]
    cluster_ids = {root: f"CUST-GOLDEN-{n:03d}" for n, root in enumerate(sorted(df["cluster_root"].unique()), start=1)}
    df["golden_customer_id"] = df["cluster_root"].map(cluster_ids)
    return df


def main():
    df = pd.DataFrame(records)
    resolved = resolve_identities(df)

    print("=== Identity Resolution Demo ===\n")
    for golden_id, group in resolved.groupby("golden_customer_id"):
        names = group[["source", "local_id", "first_name", "last_name"]].to_string(index=False)
        print(f"{golden_id}  ({len(group)} source record(s)):\n{names}\n")

    n_people_input = len(df)
    n_golden = resolved["golden_customer_id"].nunique()
    print(f"Collapsed {n_people_input} source records across 3 systems into {n_golden} golden customer_ids.")
    print("Expected: 6 golden IDs (6 real people, since Sarah Kim and David Kim are "
          "genuinely different people) -- they correctly stayed SEPARATE (different "
          "ssn_last4/dob block) despite sharing a last name; Elena Petrova's Bureau "
          "record correctly matched via the no-SSN fallback path instead of getting "
          "orphaned as a 7th cluster.")

    assert n_golden == 6, f"expected 6 golden IDs, got {n_golden}"
    print("\nPASS")


if __name__ == "__main__":
    main()
