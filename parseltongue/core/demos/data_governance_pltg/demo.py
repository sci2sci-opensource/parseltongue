"""
Demo: Biopharma Data Governance — Cross-Layer Consistency.

Scenario: A biopharma company maintains three layers of data governance:
  1. Technical catalog (CSVs) — what actually exists in the data platform
  2. Contracts (.md) — legal agreements with external data providers
  3. Business catalog (.md) — business-facing data product descriptions

Each layer is authored and maintained independently. Over time, drift
accumulates: paths change, contracts expire, business catalog entries
reference datasets that no longer exist, refresh frequencies diverge.

This demo loads all three layers as Parseltongue documents, extracts
facts from each, and runs cross-layer consistency checks. A synthetic
generator (generate.py) injects ~15-20% corruptions across layers,
and Parseltongue catches every one.

Run:
    python generate.py --clean   # first, generate the data
    python demo.py               # then, run the consistency checks
"""

import csv
import json
import logging
import re
import sys
from pathlib import Path

from parseltongue.core import System, load_source
from parseltongue.core.demos.data_governance_pltg.operators import GOVERNANCE_EFFECTS

RESOURCES = Path(__file__).parent / "resources"


# ── document loading ─────────────────────────────────────────────────


def load_all_documents(system: System):
    """Load every resource file as a named document."""
    count = 0

    # Technical catalogs (CSVs)
    tech_dir = RESOURCES / "technical_catalog"
    for csv_file in sorted(tech_dir.glob("*.csv")):
        name = f"tech:{csv_file.stem}"
        system.load_document(name, str(csv_file))
        count += 1

    # Contracts
    ctr_dir = RESOURCES / "contracts"
    for md_file in sorted(ctr_dir.glob("*.md")):
        name = f"contract:{md_file.stem}"
        system.load_document(name, str(md_file))
        count += 1

    # Business catalog
    biz_dir = RESOURCES / "business_catalog"
    for md_file in sorted(biz_dir.glob("*.md")):
        name = f"business:{md_file.stem}"
        system.load_document(name, str(md_file))
        count += 1

    return count


# ── fact extraction ──────────────────────────────────────────────────


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def extract_technical_facts(system: System) -> dict:
    """Extract facts from technical catalog CSVs.

    Returns {dataset_id: {name, path, table, cadence, source_type, provider, dept, doc_name}}
    """
    tech_dir = RESOURCES / "technical_catalog"
    datasets = {}

    for csv_file in sorted(tech_dir.glob("*.csv")):
        dept = csv_file.stem
        doc_name = f"tech:{dept}"

        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ds_id = row["dataset_id"]
                safe_id = ds_id.lower().replace("-", "_")
                datasets[ds_id] = {
                    "name": row["name"],
                    "path": row["storage_path"],
                    "table": row["table_name"],
                    "cadence": row["refresh_cadence"],
                    "source_type": row["source_type"],
                    "provider": row["provider"],
                    "owner": row["owner"],
                    "dept": dept,
                    "doc_name": doc_name,
                    "safe_id": safe_id,
                }

                # Emit facts
                load_source(
                    system,
                    f"""
                    (fact {safe_id}-path "{_escape(row['storage_path'])}"
                      :evidence (evidence "{doc_name}"
                        :quotes ("{_escape(row['storage_path'])}")
                        :explanation "Storage path for {_escape(row['name'])}"))

                    (fact {safe_id}-cadence "{row['refresh_cadence']}"
                      :evidence (evidence "{doc_name}"
                        :quotes ("{row['refresh_cadence']}")
                        :explanation "Refresh cadence for {_escape(row['name'])}"))

                    (fact {safe_id}-table "{_escape(row['table_name'])}"
                      :evidence (evidence "{doc_name}"
                        :quotes ("{_escape(row['table_name'])}")
                        :explanation "Table name for {_escape(row['name'])}"))

                    (fact {safe_id}-source-type "{row['source_type']}"
                      :evidence (evidence "{doc_name}"
                        :quotes ("{row['source_type']}")
                        :explanation "Source type for {_escape(row['name'])}"))

                    (fact {safe_id}-owner "{_escape(row['owner'])}"
                      :evidence (evidence "{doc_name}"
                        :quotes ("{_escape(row['owner'])}")
                        :explanation "Owner of {_escape(row['name'])}"))
                """,
                )

    return datasets


def extract_contract_facts(system: System) -> dict:
    """Extract facts from contract .md files.

    Returns {provider_slug: {provider, datasets: [{dataset_id, permitted_use}],
             sla, retention, classification, expiry, status, doc_name}}
    """
    ctr_dir = RESOURCES / "contracts"
    contracts = {}

    for md_file in sorted(ctr_dir.glob("*.md")):
        slug = md_file.stem
        doc_name = f"contract:{slug}"
        text = md_file.read_text()

        # Parse fields
        provider = _md_field(text, "Provider") or slug
        sla = _md_field(text, "Refresh SLA") or "unknown"
        retention = _md_field(text, "Retention Limit") or "unknown"
        classification = _md_field(text, "Data Classification") or "unknown"
        expiry = _md_field(text, "Expiry Date") or "unknown"
        status = _md_field(text, "Status") or "unknown"

        # Parse covered datasets table
        covered = []
        for m in re.finditer(r"\|\s*(DS-\d+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|", text):
            covered.append(
                {
                    "dataset_id": m.group(1).strip(),
                    "name": m.group(2).strip(),
                    "permitted_use": m.group(3).strip(),
                }
            )

        safe_slug = slug.replace("-", "_")
        contracts[slug] = {
            "provider": provider,
            "datasets": covered,
            "sla": sla,
            "retention": retention,
            "classification": classification,
            "expiry": expiry,
            "status": status,
            "doc_name": doc_name,
            "safe_slug": safe_slug,
        }

        # Emit facts
        load_source(
            system,
            f"""
            (fact ctr-{safe_slug}-sla "{sla}"
              :evidence (evidence "{doc_name}"
                :quotes ("{sla}")
                :explanation "Refresh SLA for {_escape(provider)} contract"))

            (fact ctr-{safe_slug}-retention "{_escape(retention)}"
              :evidence (evidence "{doc_name}"
                :quotes ("{_escape(retention)}")
                :explanation "Retention limit for {_escape(provider)} contract"))

            (fact ctr-{safe_slug}-classification "{classification}"
              :evidence (evidence "{doc_name}"
                :quotes ("{classification}")
                :explanation "Data classification for {_escape(provider)} contract"))

            (fact ctr-{safe_slug}-expiry "{expiry}"
              :evidence (evidence "{doc_name}"
                :quotes ("{expiry}")
                :explanation "Expiry date for {_escape(provider)} contract"))

            (fact ctr-{safe_slug}-status "{status}"
              :evidence (evidence "{doc_name}"
                :quotes ("{status}")
                :explanation "Contract status for {_escape(provider)}"))
        """,
        )

        # Facts for each covered dataset
        for ds in covered:
            ds_safe = ds["dataset_id"].lower().replace("-", "_")
            load_source(
                system,
                f"""
                (fact ctr-{safe_slug}-covers-{ds_safe} true
                  :evidence (evidence "{doc_name}"
                    :quotes ("{_escape(ds['dataset_id'])}")
                    :explanation "{_escape(provider)} contract covers {_escape(ds['name'])}"))

                (fact ctr-{safe_slug}-use-{ds_safe} "{ds['permitted_use']}"
                  :evidence (evidence "{doc_name}"
                    :quotes ("{_escape(ds['permitted_use'])}")
                    :explanation "Permitted use for {_escape(ds['name'])} under {_escape(provider)}"))
            """,
            )

    return contracts


def extract_business_facts(system: System) -> dict:
    """Extract facts from business catalog .md files.

    Returns {product_slug: {name, owner, classification, refresh, sources: [{dataset_id}], doc_name}}
    """
    biz_dir = RESOURCES / "business_catalog"
    products = {}

    for md_file in sorted(biz_dir.glob("*.md")):
        slug = md_file.stem
        doc_name = f"business:{slug}"
        text = md_file.read_text()

        name = _md_heading(text) or slug
        owner = _md_field(text, "Owner") or "unknown"
        classification = _md_field(text, "Classification") or "unknown"
        refresh = _md_field(text, "Refresh Frequency") or "unknown"
        retention_raw = _md_field(text, "Data Retention") or "unlimited"
        retention_days = 0
        ret_m = re.search(r"(\d+)\s*days", retention_raw)
        if ret_m:
            retention_days = int(ret_m.group(1))

        # Parse source datasets table (6 columns: id, name, domain, source_type, storage_path, table_name)
        sources = []
        for m in re.finditer(
            r"\|\s*(DS-\d+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|",
            text,
        ):
            sources.append(
                {
                    "dataset_id": m.group(1).strip(),
                    "name": m.group(2).strip(),
                    "domain": m.group(3).strip(),
                    "source_type": m.group(4).strip(),
                    "storage_path": m.group(5).strip(),
                    "table_name": m.group(6).strip(),
                }
            )

        safe_slug = slug.replace("-", "_")
        products[slug] = {
            "name": name,
            "owner": owner,
            "classification": classification,
            "refresh": refresh,
            "retention_days": retention_days,
            "sources": sources,
            "doc_name": doc_name,
            "safe_slug": safe_slug,
        }

        # Emit facts
        load_source(
            system,
            f"""
            (fact bp-{safe_slug}-owner "{_escape(owner)}"
              :evidence (evidence "{doc_name}"
                :quotes ("{_escape(owner)}")
                :explanation "Owner of {_escape(name)}"))

            (fact bp-{safe_slug}-classification "{classification}"
              :evidence (evidence "{doc_name}"
                :quotes ("{classification}")
                :explanation "Classification of {_escape(name)}"))

            (fact bp-{safe_slug}-refresh "{refresh}"
              :evidence (evidence "{doc_name}"
                :quotes ("{refresh}")
                :explanation "Refresh frequency of {_escape(name)}"))
        """,
        )

        # Facts for each source dataset reference
        for src in sources:
            ds_safe = src["dataset_id"].lower().replace("-", "_")
            load_source(
                system,
                f"""
                (fact bp-{safe_slug}-uses-{ds_safe} true
                  :evidence (evidence "{doc_name}"
                    :quotes ("{_escape(src['dataset_id'])}")
                    :explanation "{_escape(name)} uses {_escape(src['name'])}"))
            """,
            )

    return products


def _md_field(text: str, label: str) -> str | None:
    m = re.search(rf"\*\*{re.escape(label)}\*\*:\s*(.+)", text)
    return m.group(1).strip() if m else None


def _md_heading(text: str) -> str | None:
    m = re.search(r"^# .+:\s*(.+)", text, re.MULTILINE)
    return m.group(1).strip() if m else None


# ── cross-layer checks ──────────────────────────────────────────────


def check_contract_coverage(system: System, datasets: dict, contracts: dict):
    """Every external dataset should have a contract covering it."""
    # Build set of dataset_ids covered by any contract
    covered_ids = set()
    for ctr in contracts.values():
        for ds in ctr["datasets"]:
            covered_ids.add(ds["dataset_id"])

    issues = []
    for ds_id, ds in datasets.items():
        if ds["source_type"] == "external":
            safe_id = ds["safe_id"]
            has_contract = ds_id in covered_ids

            load_source(
                system,
                f"""
                (fact {safe_id}-has-contract {"true" if has_contract else "false"}
                  :origin "Derived from contract coverage analysis")
            """,
            )

            if not has_contract:
                issues.append(f"  MISSING CONTRACT: {ds_id} ({ds['name']}) from {ds['provider']}")

                load_source(
                    system,
                    f"""
                    (derive {safe_id}-coverage-gap
                        (= {safe_id}-has-contract false)
                        :using ({safe_id}-has-contract))
                """,
                )

    return issues


def check_sla_consistency(system: System, datasets: dict, contracts: dict):
    """Contract refresh SLA should match technical cadence for covered datasets."""
    cadence_order = {"real-time": 0, "hourly": 1, "daily": 2, "weekly": 3, "monthly": 4, "quarterly": 5}
    issues = []

    for ctr_slug, ctr in contracts.items():
        safe_slug = ctr["safe_slug"]
        for ds_entry in ctr["datasets"]:
            ds_id = ds_entry["dataset_id"]
            if ds_id not in datasets:
                continue
            ds = datasets[ds_id]
            safe_id = ds["safe_id"]

            tech_cadence = ds["cadence"]
            ctr_sla = ctr["sla"]

            matches = tech_cadence == ctr_sla
            if not matches:
                issues.append(
                    f"  SLA MISMATCH: {ds_id} ({ds['name']}) — " f"technical={tech_cadence}, contract={ctr_sla}"
                )

                load_source(
                    system,
                    f"""
                    (diff sla-check-{safe_id}
                        :replace {safe_id}-cadence
                        :with ctr-{safe_slug}-sla)
                """,
                )

    return issues


def check_referential_integrity(system: System, datasets: dict, products: dict):
    """Business product source datasets should exist in the technical catalog."""
    issues = []

    for bp_slug, bp in products.items():
        safe_slug = bp["safe_slug"]
        for src in bp["sources"]:
            ds_id = src["dataset_id"]
            ds_safe = ds_id.lower().replace("-", "_")
            exists = ds_id in datasets

            if not exists:
                issues.append(
                    f"  PHANTOM REFERENCE: {bp['name']} references {ds_id} "
                    f"({src['name']}) — not in technical catalog"
                )

                load_source(
                    system,
                    f"""
                    (fact {ds_safe}-exists-in-tech false
                      :origin "Dataset {ds_id} not found in any technical catalog CSV")

                    (derive bp-{safe_slug}-phantom-{ds_safe}
                        (= {ds_safe}-exists-in-tech false)
                        :using ({ds_safe}-exists-in-tech))
                """,
                )

    return issues


def check_refresh_consistency(system: System, datasets: dict, products: dict):
    """Business product refresh should match fastest source dataset cadence."""
    cadence_order = {"real-time": 0, "hourly": 1, "daily": 2, "weekly": 3, "monthly": 4, "quarterly": 5}
    issues = []

    for bp_slug, bp in products.items():
        safe_slug = bp["safe_slug"]
        bp_refresh = bp["refresh"]

        # Find fastest source cadence
        source_cadences = []
        for src in bp["sources"]:
            ds_id = src["dataset_id"]
            if ds_id in datasets:
                source_cadences.append(datasets[ds_id]["cadence"])

        if not source_cadences:
            continue

        fastest = min(source_cadences, key=lambda c: cadence_order.get(c, 99))
        if bp_refresh != fastest:
            issues.append(f"  REFRESH MISMATCH: {bp['name']} says {bp_refresh}, " f"fastest source is {fastest}")

    return issues


def check_expired_contracts(system: System, contracts: dict):
    """Flag contracts with status=expired that still cover active datasets."""
    issues = []
    for ctr_slug, ctr in contracts.items():
        if ctr["status"] == "expired":
            ds_names = ", ".join(d["name"] for d in ctr["datasets"])
            issues.append(
                f"  EXPIRED CONTRACT: {ctr['provider']} (expired {ctr['expiry']}) " f"still covers: {ds_names}"
            )
    return issues


def check_classification_conflicts(system: System, products: dict, contracts: dict):
    """Business product classification should not be weaker than contract classification."""
    strength = {"restricted": 0, "confidential": 1, "internal": 2, "public": 3}
    issues = []

    # Build dataset_id → contract classification map
    ds_contract_class = {}
    for ctr in contracts.values():
        for ds in ctr["datasets"]:
            ds_contract_class[ds["dataset_id"]] = ctr["classification"]

    for bp_slug, bp in products.items():
        bp_class = bp["classification"]
        bp_strength = strength.get(bp_class, 99)

        for src in bp["sources"]:
            ds_id = src["dataset_id"]
            if ds_id in ds_contract_class:
                ctr_class = ds_contract_class[ds_id]
                ctr_strength = strength.get(ctr_class, 99)

                if bp_strength > ctr_strength:
                    issues.append(
                        f"  CLASSIFICATION CONFLICT: {bp['name']} is '{bp_class}' "
                        f"but source {ds_id} contract requires '{ctr_class}'"
                    )

    return issues


def check_path_drift(system: System, datasets: dict, products: dict):
    """Business catalog storage_path should match technical catalog storage_path."""
    issues = []

    for bp_slug, bp in products.items():
        for src in bp["sources"]:
            ds_id = src["dataset_id"]
            if ds_id not in datasets:
                continue
            bp_path = src.get("storage_path", "")
            tech_path = datasets[ds_id]["path"]
            if bp_path and bp_path != tech_path:
                issues.append(
                    f"  PATH DRIFT: {bp['name']} expects {ds_id} at {bp_path}, " f"technical catalog says {tech_path}"
                )

    return issues


def check_table_rename(system: System, datasets: dict, products: dict):
    """Business catalog table_name should match technical catalog table_name."""
    issues = []

    for bp_slug, bp in products.items():
        for src in bp["sources"]:
            ds_id = src["dataset_id"]
            if ds_id not in datasets:
                continue
            bp_table = src.get("table_name", "")
            tech_table = datasets[ds_id]["table"]
            if bp_table and bp_table != tech_table:
                issues.append(
                    f"  TABLE RENAME: {bp['name']} expects {ds_id} table '{bp_table}', "
                    f"technical catalog says '{tech_table}'"
                )

    return issues


def check_retention_conflicts(system: System, products: dict, contracts: dict):
    """Business product retention should not exceed contract retention limits."""
    issues = []

    # Build dataset_id → minimum contract retention
    ds_retention: dict[str, int] = {}
    for ctr in contracts.values():
        ret_m = re.search(r"(\d+)", ctr["retention"])
        if not ret_m:
            continue
        ctr_days = int(ret_m.group(1))
        for ds in ctr["datasets"]:
            existing = ds_retention.get(ds["dataset_id"])
            if existing is None or ctr_days < existing:
                ds_retention[ds["dataset_id"]] = ctr_days

    for bp_slug, bp in products.items():
        bp_retention = bp.get("retention_days", 0)
        if bp_retention == 0:
            continue

        for src in bp["sources"]:
            ds_id = src["dataset_id"]
            if ds_id in ds_retention:
                ctr_ret = ds_retention[ds_id]
                if bp_retention > ctr_ret:
                    issues.append(
                        f"  RETENTION CONFLICT: {bp['name']} claims {bp_retention} days "
                        f"but {ds_id} contract limits to {ctr_ret} days"
                    )

    return issues


def check_owner_department(system: System, products: dict):
    """Business product owner should belong to the product's primary department."""
    dept_owners = {
        "discovery": {"Dr. Elena Rossi", "Dr. James Okafor", "Dr. Wei Zhang", "Dr. Priya Sharma"},
        "translational": {"Dr. Sarah Chen", "Dr. Marcus Rivera", "Dr. Yuki Tanaka", "Dr. Amir Hassan"},
        "clinical": {"Dr. Lisa Patel", "Dr. Robert Kim", "Dr. Fatima Al-Said", "Dr. Thomas Weber"},
        "commercial": {"Jennifer Liu", "Michael Torres", "Anna Kowalski", "David Osei"},
    }
    issues = []

    for bp_slug, bp in products.items():
        owner = bp["owner"]
        # Determine primary department from source domains
        domain_counts: dict[str, int] = {}
        for src in bp["sources"]:
            d = src.get("domain", "")
            if d:
                domain_counts[d] = domain_counts.get(d, 0) + 1
        if not domain_counts:
            continue
        primary_dept = max(domain_counts, key=domain_counts.get)

        if primary_dept in dept_owners and owner not in dept_owners[primary_dept]:
            # Find which dept the owner actually belongs to
            actual_dept = "unknown"
            for dept, owners in dept_owners.items():
                if owner in owners:
                    actual_dept = dept
                    break
            issues.append(
                f"  OWNER DRIFT: {bp['name']} primary dept is {primary_dept} "
                f"but owner '{owner}' belongs to {actual_dept}"
            )

    return issues


# ── main ─────────────────────────────────────────────────────────────


def main():
    plog = logging.getLogger("parseltongue")
    plog.setLevel(logging.WARNING)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    system = System(overridable=True, effects=GOVERNANCE_EFFECTS)
    print("=" * 72)
    print("Parseltongue — Biopharma Data Governance Cross-Layer Consistency")
    print("=" * 72)

    # Phase 0: Load documents
    print("\n--- Phase 0: Load all documents ---")
    n_docs = load_all_documents(system)
    print(f"  Loaded {n_docs} documents")

    # Phase 1: Extract technical facts
    print("\n--- Phase 1: Extract technical catalog facts ---")
    datasets = extract_technical_facts(system)
    n_internal = sum(1 for d in datasets.values() if d["source_type"] == "internal")
    n_external = sum(1 for d in datasets.values() if d["source_type"] == "external")
    print(f"  {len(datasets)} datasets ({n_internal} internal, {n_external} external)")

    # Phase 2: Extract contract facts
    print("\n--- Phase 2: Extract contract facts ---")
    contracts = extract_contract_facts(system)
    n_covered = sum(len(c["datasets"]) for c in contracts.values())
    print(f"  {len(contracts)} contracts covering {n_covered} datasets")

    # Phase 3: Extract business catalog facts
    print("\n--- Phase 3: Extract business catalog facts ---")
    products = extract_business_facts(system)
    n_sources = sum(len(p["sources"]) for p in products.values())
    print(f"  {len(products)} data products referencing {n_sources} source datasets")

    # Phase 4: Cross-layer checks
    print("\n--- Phase 4: Cross-layer consistency checks ---")
    all_issues = []

    print("\n  [Check 1] Contract coverage (every external dataset has a contract)")
    issues = check_contract_coverage(system, datasets, contracts)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ All external datasets have contracts")

    print("\n  [Check 2] SLA consistency (contract SLA matches technical cadence)")
    issues = check_sla_consistency(system, datasets, contracts)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ All SLAs match technical cadences")

    print("\n  [Check 3] Referential integrity (business products reference existing datasets)")
    issues = check_referential_integrity(system, datasets, products)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ All business product references are valid")

    print("\n  [Check 4] Refresh consistency (business refresh matches source cadences)")
    issues = check_refresh_consistency(system, datasets, products)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ All refresh frequencies are consistent")

    print("\n  [Check 5] Expired contracts")
    issues = check_expired_contracts(system, contracts)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ No expired contracts")

    print("\n  [Check 6] Classification conflicts (business vs contract classification)")
    issues = check_classification_conflicts(system, products, contracts)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ No classification conflicts")

    print("\n  [Check 7] Path drift (business catalog paths vs technical catalog)")
    issues = check_path_drift(system, datasets, products)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ All storage paths are consistent")

    print("\n  [Check 8] Table rename (business catalog tables vs technical catalog)")
    issues = check_table_rename(system, datasets, products)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ All table names are consistent")

    print("\n  [Check 9] Retention conflicts (business retention vs contract limits)")
    issues = check_retention_conflicts(system, products, contracts)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ No retention conflicts")

    print("\n  [Check 10] Owner department alignment")
    issues = check_owner_department(system, products)
    all_issues.extend(issues)
    for i in issues:
        print(i)
    if not issues:
        print("  ✓ All product owners match their department")

    # Phase 5: System consistency report
    print("\n--- Phase 5: Parseltongue consistency report ---")
    report = system.consistency()
    print(f"  {report}")

    # Summary
    print("\n" + "=" * 72)
    print(f"Data estate: {len(datasets)} datasets, {len(contracts)} contracts, {len(products)} products")
    print(f"Issues found: {len(all_issues)}")
    if all_issues:
        by_type = {}
        for issue in all_issues:
            # Extract the type (first word after the indent)
            parts = issue.strip().split(":")
            itype = parts[0] if parts else "OTHER"
            by_type[itype] = by_type.get(itype, 0) + 1
        for itype, count in sorted(by_type.items()):
            print(f"  {itype}: {count}")

    # Cross-check against manifest if available
    manifest_path = Path(__file__).parent / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        n_injected = len(manifest["corruptions"])
        print(f"\nManifest: {n_injected} corruptions were injected")
        print(f"Detection coverage: {len(all_issues)}/{n_injected} issues surfaced")

    print(f"\nFinal system: {system}")


if __name__ == "__main__":
    main()
