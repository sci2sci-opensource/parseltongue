# Data Governance Registration Protocol

**Version:** 2.1
**Owner:** Data Platform Engineering

## Purpose
 
This protocol defines the naming convention and mandatory registration requirements for all datasets, contracts, and data products in the enterprise data platform. Every entity must be registered as a set of named facts following the conventions below. Automated compliance checks discover and validate registrations by parsing source catalogs and matching fact names against these patterns.

## 1. Dataset Registration

Every dataset in the technical catalog must produce the following facts, where `{id}` is the lowercase dataset identifier with hyphens replaced by underscores (e.g., DS-1234 becomes ds_1234):

| Fact Name Pattern       | Type   | Description                       |
|------------------------|--------|-----------------------------------|
| `{id}-path`            | string | Storage path in the data platform |
| `{id}-cadence`         | string | Refresh cadence (daily, weekly…)  |
| `{id}-source-type`     | string | "internal" or "commercial"        |
| `{id}-table`           | string | Table name in the warehouse       |
| `{id}-owner`           | string | Responsible person or team        |

A dataset is **fully registered** when all five facts are present. A dataset with fewer than five facts is **partially registered** and must be remediated.

## 2. Contract Registration

Every provider contract must produce the following facts, where `{slug}` is the provider name slug (e.g., iqvia, flatiron_health):

| Fact Name Pattern              | Type   | Description                          |
|-------------------------------|--------|--------------------------------------|
| `ctr-{slug}-sla`             | string | Contractual refresh SLA              |
| `ctr-{slug}-retention`       | string | Retention limit text                 |
| `ctr-{slug}-classification`  | string | Data classification level            |
| `ctr-{slug}-expiry`          | string | Contract expiry date                 |
| `ctr-{slug}-status`          | string | "active" or "expired"                |
| `ctr-{slug}-covers-{ds_id}`  | bool   | Whether contract covers this dataset |
| `ctr-{slug}-use-{ds_id}`     | string | Permitted use for this dataset       |

A contract is **fully registered** when the first five facts are present. Coverage and use facts are per-dataset extensions.

## 3. Business Product Registration

Every business data product must produce the following facts, where `{slug}` is the product name slug:

| Fact Name Pattern             | Type   | Description                          |
|------------------------------|--------|--------------------------------------|
| `bp-{slug}-owner`            | string | Product owner                        |
| `bp-{slug}-classification`   | string | Product classification level         |
| `bp-{slug}-refresh`          | string | Advertised refresh frequency         |
| `bp-{slug}-uses-{ds_id}`     | bool   | Whether product consumes this source |

A product is **fully registered** when the first three facts are present.

## 4. Compliance Discovery

The compliance checker discovers entities by parsing source documents:
- Technical catalog CSVs are parsed row-by-row; each row's `dataset_id` column identifies a dataset.
- Contract markdown files are parsed for provider metadata and covered-dataset tables.
- Business catalog markdown files are parsed for product metadata and source-dataset tables.

For each discovered entity, the checker constructs expected fact names from the patterns above and verifies their existence. Missing facts indicate incomplete registration.

## 5. Cross-Layer Validation

After verifying registration completeness, the checker applies policy rules (defined in the governance policy) to validate cross-layer consistency:
- Commercial datasets must have active contracts with specified use policies.
- Product classification must be at least as restrictive as its most restrictive source.
- Technical refresh cadence must not exceed contractual SLA.
- Business catalog paths and tables must match technical catalog.
- Product retention must not exceed contractual limits.

Violations are counted per rule. A dataset estate is **policy-consistent** when the total violation count across all rules is zero.
