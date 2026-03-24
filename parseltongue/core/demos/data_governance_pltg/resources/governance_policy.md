# Enterprise Data Governance Policy

**Effective Date:** 2024-01-15
**Version:** 3.2
**Owner:** Chief Data Officer

## 1. Data Classification

All datasets in the enterprise data platform must carry one of four classification levels: **public**, **internal**, **confidential**, or **restricted**. Classification is assigned at ingestion and propagated through the lineage graph.

### 1.1 Classification Propagation

Any data product that consumes a restricted source dataset must itself be classified as restricted. A product's effective classification is the most restrictive classification among all its source datasets. A product classified below its effective classification is in violation.

### 1.2 Omics Data

All genomic, proteomic, and transcriptomic datasets — collectively "omics data" — are classified as restricted regardless of their origin. Omics data shall not appear as a source in any data product classified below restricted.

### 1.3 Patient-Level Data

Datasets containing patient-level records are classified as confidential at minimum. Patient-level data with genomic markers is classified as restricted.

## 2. Contract Requirements

### 2.1 Commercial Dataset Contracts

Any dataset sourced from a commercial provider must be covered by a contract with valid start and end dates and a specified permitted-use policy. A commercial dataset without a valid contract, or with an expired contract, is non-compliant and must be quarantined.

### 2.2 Contract Validity

A contract is valid when its status is "active" and its expiry date has not passed. An expired contract revokes all permitted uses for the datasets it covers. Data products consuming datasets covered only by expired contracts must be flagged for review.

### 2.3 Permitted Use

Each contract specifies permitted uses for the datasets it covers. A data product may only consume a dataset for a use that falls within the contract's permitted-use scope. Using a dataset outside its permitted use is a policy violation.

## 3. Refresh and SLA

### 3.1 SLA Alignment

The contractual refresh SLA for a dataset must be at least as frequent as the technical refresh cadence configured in the data platform. If the technical cadence is faster than the contractual SLA, the platform may be pulling data more frequently than the provider guarantees, creating a reliability risk.

### 3.2 Product Refresh

A data product's advertised refresh frequency must not exceed the slowest refresh cadence among its source datasets. Advertising a faster refresh than sources can deliver is misleading.

## 4. Retention

### 4.1 Retention Limits

Data products must not retain records longer than the shortest retention limit specified by any contract covering their source datasets. Where no contract specifies a limit, the enterprise default of 730 days applies.

### 4.2 Regulatory Hold

Retention limits may be extended by a documented regulatory hold. Without an active hold, exceeding the contractual retention limit is a violation.

## 5. Lineage and Referential Integrity

### 5.1 Source Existence

Every dataset referenced by a data product must exist in the technical catalog. A reference to a non-existent dataset is a phantom reference and indicates catalog drift.

### 5.2 Path Consistency

The storage path recorded in the business catalog for a source dataset must match the path in the technical catalog. Path divergence indicates that the business catalog is stale.

### 5.3 Table Consistency

The table name recorded in the business catalog for a source dataset must match the table name in the technical catalog. Table name divergence indicates a schema migration that was not propagated to the business catalog.

## 6. Ownership

### 6.1 Domain Alignment

The owner of a data product should belong to the department that owns the majority of the product's source datasets. Cross-department ownership requires documented approval from both department heads.
