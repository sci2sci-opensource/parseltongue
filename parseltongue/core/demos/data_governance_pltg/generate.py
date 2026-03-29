"""
Synthetic data generator for the data_governance_pltg demo.

Two phases:
  1. Generate a fully consistent biopharma data estate
     - 4 technical catalog CSVs (discovery, translational, clinical, commercial)
     - ~25-30 contract .md files (external providers only)
     - ~60-80 business catalog .md product files
  2. Inject inconsistencies (~15-20% of records) across all three layers,
     logging every mutation to manifest.json

Run:
    python generate.py            # generate into resources/
    python generate.py --clean    # wipe resources/ and regenerate
"""

import argparse
import csv
import json
import random
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

SEED = 42
RESOURCES = Path(__file__).parent / "resources"

# ── helpers ──────────────────────────────────────────────────────────


def _id(prefix: str, n: int) -> str:
    return f"{prefix}-{n:04d}"


def _date(start: str = "2021-01-01", end: str = "2025-12-31") -> str:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    d = s + timedelta(days=random.randint(0, (e - s).days))
    return d.isoformat()


def _future_date() -> str:
    return _date("2026-06-01", "2029-12-31")


def _past_date() -> str:
    return _date("2020-01-01", "2024-06-01")


def _pick(choices):
    return random.choice(choices)


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_").replace("/", "_")


# ── domain knowledge ────────────────────────────────────────────────

CADENCES = ["real-time", "hourly", "daily", "weekly", "monthly", "quarterly"]
FORMATS = ["parquet", "csv", "json", "avro", "bam", "fastq", "vcf", "dicom", "sas7bdat"]
CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"]
PERMITTED_USES = ["research-only", "internal-analytics", "commercial", "all"]
GEO_RESTRICTIONS = ["US-only", "EU-only", "global", "APAC-only"]

OWNERS_DISCOVERY = ["Dr. Elena Rossi", "Dr. James Okafor", "Dr. Wei Zhang", "Dr. Priya Sharma"]
OWNERS_TRANSLATIONAL = ["Dr. Sarah Chen", "Dr. Marcus Rivera", "Dr. Yuki Tanaka", "Dr. Amir Hassan"]
OWNERS_CLINICAL = ["Dr. Lisa Patel", "Dr. Robert Kim", "Dr. Fatima Al-Said", "Dr. Thomas Weber"]
OWNERS_COMMERCIAL = ["Jennifer Liu", "Michael Torres", "Anna Kowalski", "David Osei"]


# ── dataset templates ───────────────────────────────────────────────


@dataclass
class DatasetRecord:
    dataset_id: str
    name: str
    storage_path: str
    table_name: str
    schema_columns: str
    format: str
    refresh_cadence: str
    source_type: str  # internal | external
    provider: str  # "internal" or vendor name
    owner: str
    created_date: str
    row_count: int
    department: str = ""  # not written to CSV, used for bookkeeping


@dataclass
class ContractRecord:
    contract_id: str
    provider: str
    effective_date: str
    expiry_date: str
    status: str
    covered_datasets: List[Dict]  # [{dataset_id, name, permitted_use}]
    refresh_sla: str
    retention_limit_days: int
    classification: str
    geo_restriction: str
    deidentification_required: bool
    audit_rights: str


@dataclass
class BusinessProduct:
    product_id: str
    name: str
    owner: str
    classification: str
    refresh_frequency: str
    created_date: str
    description: str
    source_datasets: List[Dict]  # [{dataset_id, name, domain, source_type, storage_path, table_name}]
    retention_days: int  # max retention across source contracts (or 0 if all internal)
    completeness_pct: float
    last_validated: str
    known_limitations: str
    consumers: List[str]
    request_process: str


# ── phase 1: consistent generation ──────────────────────────────────

DISCOVERY_DATASETS = [
    (
        "HTS Primary Screen Library",
        "s3://discovery-lake/hts/primary_screen",
        "hts_primary_screen",
        "compound_id|smiles|activity_uM|target|assay_type|plate_id|well|z_score",
        "parquet",
        "weekly",
        "internal",
    ),
    (
        "HTS Confirmation Screen",
        "s3://discovery-lake/hts/confirmation",
        "hts_confirmation",
        "compound_id|smiles|ic50_nM|hill_slope|r_squared|assay_date",
        "parquet",
        "weekly",
        "internal",
    ),
    (
        "SAR Analysis Tables",
        "s3://discovery-lake/sar/analyses",
        "sar_analysis",
        "series_id|compound_id|activity|selectivity|admet_flags|iteration",
        "parquet",
        "daily",
        "internal",
    ),
    (
        "Target Validation Assays",
        "s3://discovery-lake/targets/validation",
        "target_validation",
        "target_id|gene_symbol|assay_type|knockdown_pct|cell_line|replicate",
        "csv",
        "monthly",
        "internal",
    ),
    (
        "CRISPR Screen Results",
        "s3://discovery-lake/crispr/screens",
        "crispr_screens",
        "guide_id|gene|log2fc|fdr|cell_line|library|screen_date",
        "parquet",
        "monthly",
        "internal",
    ),
    (
        "Protein Structure Models",
        "s3://discovery-lake/structures/models",
        "protein_structures",
        "pdb_id|target|resolution_A|method|ligand|binding_site_residues",
        "parquet",
        "quarterly",
        "internal",
    ),
    (
        "Fragment Library Inventory",
        "s3://discovery-lake/fragments/inventory",
        "fragment_library",
        "fragment_id|smiles|mw|clogp|hba|hbd|rotatable_bonds|stock_mg",
        "csv",
        "monthly",
        "internal",
    ),
    (
        "DMPK In Vitro ADME",
        "s3://discovery-lake/dmpk/in_vitro",
        "dmpk_adme",
        "compound_id|microsomal_clint|papp_ab|papp_ba|efflux_ratio|plasma_binding",
        "parquet",
        "weekly",
        "internal",
    ),
    (
        "Compound Selectivity Panel",
        "s3://discovery-lake/selectivity/panel",
        "selectivity_panel",
        "compound_id|kinase_panel_id|percent_inhibition|concentration_nM",
        "parquet",
        "monthly",
        "internal",
    ),
    (
        "Lead Optimization Tracker",
        "s3://discovery-lake/leads/tracker",
        "lead_optimization",
        "program_id|series|lead_compound|stage|potency_nM|selectivity_fold|pk_status",
        "csv",
        "daily",
        "internal",
    ),
    # External
    (
        "NCBI RefSeq Genome",
        "s3://ref-data/ncbi/refseq",
        "ncbi_refseq",
        "accession|organism|assembly|chromosome|seq_length|gene_count|release_date",
        "parquet",
        "quarterly",
        "external",
        "NCBI",
    ),
    (
        "Ensembl Gene Annotations",
        "s3://ref-data/ensembl/genes",
        "ensembl_genes",
        "ensembl_id|gene_symbol|biotype|chromosome|start|end|strand|description",
        "parquet",
        "quarterly",
        "external",
        "Ensembl/EMBL-EBI",
    ),
    (
        "PDB Protein Structures",
        "s3://ref-data/pdb/structures",
        "pdb_structures",
        "pdb_id|title|method|resolution|organism|chain_count|release_date",
        "parquet",
        "weekly",
        "external",
        "RCSB PDB",
    ),
    (
        "ChEMBL Bioactivity Data",
        "s3://ref-data/chembl/bioactivity",
        "chembl_bioactivity",
        "chembl_id|smiles|target_id|activity_type|value|units|assay_type|source",
        "parquet",
        "quarterly",
        "external",
        "EMBL-EBI ChEMBL",
    ),
    (
        "DrugBank Interactions",
        "s3://ref-data/drugbank/interactions",
        "drugbank_interactions",
        "drugbank_id|name|cas_number|mechanism|target_gene|pathway|interaction_type",
        "parquet",
        "quarterly",
        "external",
        "DrugBank",
    ),
    (
        "UniProt Protein Sequences",
        "s3://ref-data/uniprot/sequences",
        "uniprot_sequences",
        "uniprot_id|gene|organism|function|subcellular_location|sequence_length|reviewed",
        "parquet",
        "monthly",
        "external",
        "UniProt Consortium",
    ),
    (
        "ChemSpider Compound Registry",
        "s3://ref-data/chemspider/compounds",
        "chemspider_compounds",
        "csid|smiles|inchi|molecular_formula|mw|data_sources|synonyms",
        "csv",
        "monthly",
        "external",
        "Royal Society of Chemistry",
    ),
    (
        "ZINC20 Screening Library",
        "s3://ref-data/zinc20/library",
        "zinc20_library",
        "zinc_id|smiles|mw|logp|hba|hbd|charge|purchasability",
        "parquet",
        "quarterly",
        "external",
        "UCSF ZINC",
    ),
]

TRANSLATIONAL_DATASETS = [
    (
        "WGS Germline Runs",
        "s3://seq-lake/wgs/germline",
        "wgs_germline",
        "sample_id|patient_id|flowcell|lane|read_count|mean_coverage|qc_pass|run_date",
        "bam",
        "daily",
        "internal",
    ),
    (
        "WGS Tumor Runs",
        "s3://seq-lake/wgs/tumor",
        "wgs_tumor",
        "sample_id|patient_id|tumor_purity|ploidy|coverage|variant_count|run_date",
        "bam",
        "daily",
        "internal",
    ),
    (
        "WES Exome Captures",
        "s3://seq-lake/wes/captures",
        "wes_captures",
        "sample_id|patient_id|capture_kit|on_target_pct|mean_coverage|run_date",
        "bam",
        "daily",
        "internal",
    ),
    (
        "RNA-seq Expression",
        "s3://seq-lake/rnaseq/expression",
        "rnaseq_expression",
        "sample_id|patient_id|gene_id|tpm|fpkm|raw_count|library_type|run_date",
        "parquet",
        "daily",
        "internal",
    ),
    (
        "scRNA-seq Cell Clusters",
        "s3://seq-lake/scrnaseq/clusters",
        "scrnaseq_clusters",
        "sample_id|cell_barcode|cluster_id|cell_type|umap_x|umap_y|n_genes|n_umi",
        "parquet",
        "weekly",
        "internal",
    ),
    (
        "ELISA Biomarker Results",
        "s3://assay-lake/elisa/results",
        "elisa_results",
        "sample_id|patient_id|analyte|concentration_pg_ml|cv_pct|plate_id|run_date",
        "csv",
        "weekly",
        "internal",
    ),
    (
        "Flow Cytometry Panels",
        "s3://assay-lake/flow/panels",
        "flow_cytometry",
        "sample_id|patient_id|panel|cd_marker|pct_positive|mfi|gate|run_date",
        "csv",
        "weekly",
        "internal",
    ),
    (
        "Mass Spec Proteomics",
        "s3://assay-lake/massspec/proteomics",
        "massspec_proteomics",
        "sample_id|patient_id|protein_id|abundance|peptide_count|coverage_pct|run_date",
        "parquet",
        "weekly",
        "internal",
    ),
    (
        "Multiplex Immunoassay",
        "s3://assay-lake/multiplex/results",
        "multiplex_immunoassay",
        "sample_id|patient_id|panel_name|analyte|concentration|unit|cv_pct",
        "csv",
        "weekly",
        "internal",
    ),
    (
        "Histopathology Slides",
        "s3://imaging-lake/pathology/slides",
        "histopathology_slides",
        "slide_id|patient_id|tissue_type|stain|magnification|scanner|file_size_gb|scan_date",
        "dicom",
        "daily",
        "internal",
    ),
    (
        "Radiology DICOM Archive",
        "s3://imaging-lake/radiology/dicom",
        "radiology_dicom",
        "study_id|patient_id|modality|body_part|series_count|slice_count|study_date",
        "dicom",
        "daily",
        "internal",
    ),
    (
        "Spatial Transcriptomics",
        "s3://seq-lake/spatial/visium",
        "spatial_transcriptomics",
        "sample_id|patient_id|spot_count|gene_count|tissue_type|resolution|run_date",
        "parquet",
        "monthly",
        "internal",
    ),
    # External
    (
        "ClinVar Variant Classifications",
        "s3://ref-data/clinvar/variants",
        "clinvar_variants",
        "variation_id|gene|hgvs|clinical_significance|review_status|condition|last_evaluated",
        "vcf",
        "monthly",
        "external",
        "NCBI ClinVar",
    ),
    (
        "gnomAD Population Frequencies",
        "s3://ref-data/gnomad/frequencies",
        "gnomad_frequencies",
        "variant_id|chromosome|position|ref|alt|af_global|af_afr|af_eas|af_nfe|filter",
        "vcf",
        "quarterly",
        "external",
        "Broad Institute gnomAD",
    ),
    (
        "COSMIC Somatic Mutations",
        "s3://ref-data/cosmic/somatic",
        "cosmic_somatic",
        "cosmic_id|gene|mutation_aa|mutation_cds|primary_site|histology|sample_count",
        "parquet",
        "quarterly",
        "external",
        "Wellcome Sanger COSMIC",
    ),
    (
        "Illumina TruSight Panels",
        "s3://vendor-data/illumina/trusight",
        "illumina_trusight",
        "panel_name|gene_count|region_count|total_bases|design_version|release_date",
        "csv",
        "quarterly",
        "external",
        "Illumina",
    ),
    (
        "10x Genomics References",
        "s3://vendor-data/10x/references",
        "tenx_references",
        "reference_name|species|genome_build|gene_count|version|release_date",
        "parquet",
        "quarterly",
        "external",
        "10x Genomics",
    ),
]

CLINICAL_DATASETS = [
    (
        "Phase I Safety Trials",
        "s3://clinical-lake/trials/phase1",
        "phase1_safety",
        "trial_id|patient_id|cohort|dose_level|dose_unit|ae_grade|ae_term|visit_date",
        "sas7bdat",
        "daily",
        "internal",
    ),
    (
        "Phase II Efficacy Trials",
        "s3://clinical-lake/trials/phase2",
        "phase2_efficacy",
        "trial_id|patient_id|arm|response|best_response|pfs_months|os_months|visit_date",
        "sas7bdat",
        "daily",
        "internal",
    ),
    (
        "Phase III Pivotal Trials",
        "s3://clinical-lake/trials/phase3",
        "phase3_pivotal",
        "trial_id|patient_id|site_id|arm|primary_endpoint|secondary_endpoint|status|date",
        "sas7bdat",
        "daily",
        "internal",
    ),
    (
        "Dose Escalation Records",
        "s3://clinical-lake/trials/dose_escalation",
        "dose_escalation",
        "trial_id|cohort|dose_mg|n_patients|dlt_count|mtd_reached|decision_date",
        "csv",
        "weekly",
        "internal",
    ),
    (
        "Patient Demographics",
        "s3://clinical-lake/patients/demographics",
        "patient_demographics",
        "patient_id|age|sex|race|ethnicity|country|site_id|enrollment_date",
        "parquet",
        "daily",
        "internal",
    ),
    (
        "Lab Results (Central Lab)",
        "s3://clinical-lake/labs/central",
        "central_lab_results",
        "patient_id|visit|test_name|result_value|unit|ref_low|ref_high|flag|collection_date",
        "csv",
        "daily",
        "internal",
    ),
    (
        "ECG Monitoring Data",
        "s3://clinical-lake/monitoring/ecg",
        "ecg_monitoring",
        "patient_id|visit|hr_bpm|qtcf_ms|pr_ms|qrs_ms|interpretation|recording_date",
        "csv",
        "daily",
        "internal",
    ),
    (
        "Adverse Event Reports",
        "s3://clinical-lake/safety/ae_internal",
        "ae_internal",
        "patient_id|trial_id|ae_term|soc|grade|serious|outcome|onset_date|resolve_date",
        "csv",
        "daily",
        "internal",
    ),
    (
        "Informed Consent Tracker",
        "s3://clinical-lake/regulatory/consent",
        "consent_tracker",
        "patient_id|trial_id|consent_version|signed_date|witness|amendments|withdrawal_date",
        "csv",
        "weekly",
        "internal",
    ),
    (
        "Sample Biobank LIMS",
        "s3://clinical-lake/biobank/lims",
        "biobank_lims",
        "sample_id|patient_id|sample_type|collection_date|storage_location|volume_ml|freeze_thaw_cycles",
        "csv",
        "daily",
        "internal",
    ),
    (
        "Vital Signs Monitoring",
        "s3://clinical-lake/monitoring/vitals",
        "vitals_monitoring",
        "patient_id|visit|sbp|dbp|heart_rate|temperature|weight_kg|height_cm|date",
        "csv",
        "daily",
        "internal",
    ),
    (
        "Concomitant Medications",
        "s3://clinical-lake/patients/conmeds",
        "concomitant_meds",
        "patient_id|medication|dose|route|frequency|start_date|end_date|indication",
        "csv",
        "daily",
        "internal",
    ),
    (
        "Site Performance Metrics",
        "s3://clinical-lake/operations/site_metrics",
        "site_metrics",
        "site_id|country|enrollment_target|enrolled|screen_fail_pct|query_rate|last_updated",
        "csv",
        "weekly",
        "internal",
    ),
    (
        "Data Monitoring Committee",
        "s3://clinical-lake/oversight/dmc",
        "dmc_reports",
        "trial_id|meeting_date|recommendation|unblinded|safety_signal|interim_analysis",
        "csv",
        "quarterly",
        "internal",
    ),
    # External
    (
        "FDA FAERS Adverse Events",
        "s3://external-feeds/fda/faers",
        "fda_faers",
        "report_id|drug_name|reaction|outcome|age|sex|reporter_type|receive_date",
        "csv",
        "quarterly",
        "external",
        "FDA",
    ),
    (
        "EMA EudraVigilance Reports",
        "s3://external-feeds/ema/eudravigilance",
        "ema_eudravigilance",
        "report_id|substance|reaction_meddra|serious|outcome|age_group|region|report_date",
        "csv",
        "quarterly",
        "external",
        "EMA",
    ),
    (
        "WHO VigiBase Global Reports",
        "s3://external-feeds/who/vigibase",
        "who_vigibase",
        "report_id|drug|reaction|country|age|sex|reporter|report_type|year",
        "csv",
        "quarterly",
        "external",
        "WHO Uppsala",
    ),
    (
        "MedDRA Terminology",
        "s3://ref-data/meddra/terms",
        "meddra_terms",
        "meddra_code|pt_name|hlt_name|hlgt_name|soc_name|version",
        "csv",
        "quarterly",
        "external",
        "MedDRA MSSO",
    ),
    (
        "ICD-10 Coding Reference",
        "s3://ref-data/icd10/codes",
        "icd10_codes",
        "icd_code|description|category|chapter|block|is_billable",
        "csv",
        "quarterly",
        "external",
        "WHO ICD",
    ),
]

COMMERCIAL_DATASETS = [
    (
        "Post-Market Surveillance",
        "s3://commercial-lake/surveillance/reports",
        "post_market_surveillance",
        "product_id|event_type|description|severity|reporter|report_date|country",
        "csv",
        "weekly",
        "internal",
    ),
    (
        "Field Medical Insights",
        "s3://commercial-lake/medical/insights",
        "field_medical_insights",
        "insight_id|territory|hcp_specialty|topic|sentiment|action_needed|date",
        "csv",
        "weekly",
        "internal",
    ),
    (
        "KOL Engagement Tracker",
        "s3://commercial-lake/medical/kol_tracker",
        "kol_tracker",
        "kol_id|name|institution|specialty|tier|engagement_count|last_contact|region",
        "csv",
        "monthly",
        "internal",
    ),
    (
        "Market Access Analytics",
        "s3://commercial-lake/market_access/analytics",
        "market_access",
        "product_id|market|formulary_status|tier|payer_type|lives_covered|effective_date",
        "parquet",
        "monthly",
        "internal",
    ),
    (
        "Sales Territory Data",
        "s3://commercial-lake/sales/territories",
        "sales_territories",
        "territory_id|rep_id|region|product|scripts_trx|scripts_nrx|market_share_pct|period",
        "parquet",
        "weekly",
        "internal",
    ),
    (
        "Medical Affairs Publications",
        "s3://commercial-lake/medical/publications",
        "medical_publications",
        "pub_id|title|journal|impact_factor|pub_type|therapeutic_area|pub_date",
        "csv",
        "monthly",
        "internal",
    ),
    (
        "Launch Readiness Tracker",
        "s3://commercial-lake/launch/readiness",
        "launch_readiness",
        "product_id|market|milestone|status|owner|target_date|actual_date|risk_level",
        "csv",
        "weekly",
        "internal",
    ),
    # External
    (
        "Flatiron RWE Oncology",
        "s3://external-feeds/flatiron/oncology",
        "flatiron_oncology",
        "patient_token|diagnosis|stage|biomarkers|treatment_line|regimen|os_months|data_date",
        "parquet",
        "monthly",
        "external",
        "Flatiron Health",
    ),
    (
        "Tempus Genomic-Clinical",
        "s3://external-feeds/tempus/genomic_clinical",
        "tempus_genomic_clinical",
        "patient_token|tumor_type|panel|variants_detected|tmb|msi_status|treatment|data_date",
        "parquet",
        "monthly",
        "external",
        "Tempus Labs",
    ),
    (
        "IQVIA Prescription Data",
        "s3://external-feeds/iqvia/prescriptions",
        "iqvia_prescriptions",
        "product|ndc|channel|geography|trx_count|nrx_count|period|data_date",
        "sas7bdat",
        "weekly",
        "external",
        "IQVIA",
    ),
    (
        "Optum Claims and EHR",
        "s3://external-feeds/optum/claims_ehr",
        "optum_claims_ehr",
        "patient_token|claim_type|diagnosis_icd|procedure_cpt|ndc|paid_amount|service_date",
        "parquet",
        "monthly",
        "external",
        "Optum/UHG",
    ),
    (
        "MarketScan Commercial Claims",
        "s3://external-feeds/marketscan/claims",
        "marketscan_claims",
        "patient_token|age_group|plan_type|diagnosis|procedure|drug_ndc|paid|service_date",
        "sas7bdat",
        "monthly",
        "external",
        "Merative MarketScan",
    ),
    (
        "Symphony Health Rx Data",
        "s3://external-feeds/symphony/rx",
        "symphony_rx",
        "product|ndc|prescriber_id|pharmacy_id|quantity|days_supply|date",
        "csv",
        "weekly",
        "external",
        "Symphony Health",
    ),
    (
        "Definitive Healthcare HCP",
        "s3://external-feeds/defhc/hcp",
        "definitive_hcp",
        "npi|name|specialty|affiliation|address|prescribing_volume|tier|last_updated",
        "csv",
        "monthly",
        "external",
        "Definitive Healthcare",
    ),
]


# ── scale: expand template lists with combinatorial variations ──────

_SUFFIXES = [
    "Batch A",
    "Batch B",
    "Batch C",
    "Batch D",
    "Batch E",
    "HepG2",
    "A549",
    "MCF7",
    "HEK293",
    "Jurkat",
    "US Cohort",
    "EU Cohort",
    "APAC Cohort",
    "LATAM Cohort",
    "Phase 1",
    "Phase 2",
    "v2",
    "v3",
    "Extended",
    "QC Filtered",
    "Normalized",
    "Imputed",
    "Annotated",
]


def _scale_templates(templates: list, scale: int) -> list:
    """Expand template list by scale factor using combinatorial suffixes.

    Scale 1 = original templates (no change).
    Scale N = original + (N-1) variations per template with suffixed names/paths/tables.
    """
    if scale <= 1:
        return templates

    expanded = list(templates)
    suffixes = list(_SUFFIXES)
    for s in range(1, scale):
        for entry in templates:
            name = entry[0]
            path = entry[1]
            table = entry[2]
            suffix = suffixes[(s - 1 + hash(name)) % len(suffixes)]
            new_name = f"{name} — {suffix}"
            slug_suffix = _slug(suffix)
            new_path = f"{path}/{slug_suffix}"
            new_table = f"{table}_{slug_suffix}"
            new_entry = (new_name, new_path, new_table) + entry[3:]
            expanded.append(new_entry)
    return expanded


_seen_ids: set = set()


def _build_datasets(template_list, department, owners) -> List[DatasetRecord]:
    records = []
    for entry in template_list:
        if len(entry) == 8:
            name, path, table, schema, fmt, cadence, src_type = entry[:7]
            provider = entry[7]
        else:
            name, path, table, schema, fmt, cadence, src_type = entry
            provider = "internal"

        # Ensure globally unique dataset IDs (hash collisions across departments)
        n = hash((department, name)) % 9000 + 1000
        ds_id = _id("DS", n)
        while ds_id in _seen_ids:
            n += 1
            ds_id = _id("DS", n)
        _seen_ids.add(ds_id)
        records.append(
            DatasetRecord(
                dataset_id=ds_id,
                name=name,
                storage_path=path,
                table_name=table,
                schema_columns=schema,
                format=fmt,
                refresh_cadence=cadence,
                source_type=src_type,
                provider=provider,
                owner=_pick(owners),
                created_date=_date("2020-01-01", "2024-06-01"),
                row_count=random.randint(500, 50_000_000),
                department=department,
            )
        )
    return records


def generate_all_datasets(scale: int = 1) -> Dict[str, List[DatasetRecord]]:
    return {
        "discovery": _build_datasets(_scale_templates(DISCOVERY_DATASETS, scale), "discovery", OWNERS_DISCOVERY),
        "translational": _build_datasets(
            _scale_templates(TRANSLATIONAL_DATASETS, scale), "translational", OWNERS_TRANSLATIONAL
        ),
        "clinical": _build_datasets(_scale_templates(CLINICAL_DATASETS, scale), "clinical", OWNERS_CLINICAL),
        "commercial": _build_datasets(_scale_templates(COMMERCIAL_DATASETS, scale), "commercial", OWNERS_COMMERCIAL),
    }


# ── contracts ────────────────────────────────────────────────────────


def generate_contracts(all_datasets: Dict[str, List[DatasetRecord]]) -> List[ContractRecord]:
    # Group external datasets by provider
    by_provider: Dict[str, List[DatasetRecord]] = {}
    for dept_datasets in all_datasets.values():
        for ds in dept_datasets:
            if ds.source_type == "external":
                by_provider.setdefault(ds.provider, []).append(ds)

    contracts = []
    for i, (provider, datasets) in enumerate(sorted(by_provider.items()), 1):
        # Pick a cadence SLA that matches the fastest dataset in the group
        cadence_order = {c: j for j, c in enumerate(CADENCES)}
        fastest = min(datasets, key=lambda d: cadence_order.get(d.refresh_cadence, 99))

        effective = _date("2021-01-01", "2023-06-01")
        contracts.append(
            ContractRecord(
                contract_id=_id("CTR", i),
                provider=provider,
                effective_date=effective,
                expiry_date=_future_date(),
                status="active",
                covered_datasets=[
                    {"dataset_id": ds.dataset_id, "name": ds.name, "permitted_use": _pick(PERMITTED_USES)}
                    for ds in datasets
                ],
                refresh_sla=fastest.refresh_cadence,
                retention_limit_days=_pick([90, 180, 365, 730, 1825]),
                classification=(
                    "restricted"
                    if any(
                        re.search(r"(?i)genom|proteom|transcriptom|omics|crispr|rna.seq|wgs", ds.name)
                        for ds in datasets
                    )
                    else _pick(["confidential", "restricted"])
                ),
                geo_restriction=_pick(GEO_RESTRICTIONS),
                deidentification_required=_pick([True, False]),
                audit_rights=_pick(
                    [
                        "Annual audit with 30-day notice",
                        "Bi-annual audit with 60-day notice",
                        "Quarterly compliance review",
                        "On-demand audit with 14-day notice",
                    ]
                ),
            )
        )
    return contracts


# ── business products ────────────────────────────────────────────────

PRODUCT_TEMPLATES = [
    # (name, description_template, department_sources, n_sources_range, consumers)
    (
        "Genomic Variant Panel",
        "Integrated germline and somatic variant calls with population frequency annotations and clinical significance. Used by translational scientists for variant interpretation and biomarker discovery.",
        ["translational"],
        (2, 5),
        ["Translational Science", "Biomarker Team", "Clinical Genomics"],
    ),
    (
        "Patient 360 Profile",
        "Comprehensive patient view combining demographics, lab results, treatment history, and molecular profiling. Enables holistic patient stratification for trial enrollment and precision medicine.",
        ["clinical", "translational"],
        (3, 6),
        ["Clinical Operations", "Medical Affairs", "Translational Science"],
    ),
    (
        "Drug-Target Interaction Atlas",
        "Curated drug-target interactions combining internal screening data with public bioactivity databases. Supports target validation and lead identification.",
        ["discovery"],
        (2, 4),
        ["Discovery Chemistry", "Computational Biology", "Target Sciences"],
    ),
    (
        "Safety Signal Dashboard",
        "Aggregated adverse event data from internal trials and external pharmacovigilance databases. Powers real-time safety signal detection and regulatory reporting.",
        ["clinical"],
        (2, 5),
        ["Drug Safety", "Regulatory Affairs", "Medical Affairs"],
    ),
    (
        "Real-World Evidence Platform",
        "Integrated claims, EHR, and genomic-clinical data from multiple vendors. Supports health economics, comparative effectiveness, and label expansion studies.",
        ["commercial"],
        (2, 4),
        ["HEOR", "Medical Affairs", "Market Access"],
    ),
    (
        "Compound Optimization Suite",
        "End-to-end compound tracking from HTS hits through lead optimization. Includes ADME, selectivity, and PK data with SAR visualizations.",
        ["discovery"],
        (3, 5),
        ["Medicinal Chemistry", "DMPK", "Discovery Biology"],
    ),
    (
        "Biomarker Discovery Engine",
        "Multi-omic biomarker analysis combining proteomics, transcriptomics, and immunoassay results. Identifies predictive and prognostic biomarkers for clinical development.",
        ["translational"],
        (3, 5),
        ["Biomarker Team", "Translational Science", "Clinical Development"],
    ),
    (
        "Clinical Trial Operations Hub",
        "Centralized trial management data including site performance, enrollment tracking, consent management, and monitoring metrics.",
        ["clinical"],
        (3, 5),
        ["Clinical Operations", "CRO Partners", "Regulatory Affairs"],
    ),
    (
        "Competitive Intelligence Feed",
        "Market analytics combining prescription data, medical publications, and KOL engagement metrics for competitive landscape assessment.",
        ["commercial"],
        (2, 4),
        ["Commercial Strategy", "Medical Affairs", "Market Access"],
    ),
    (
        "Tumor Profiling Service",
        "Comprehensive tumor characterization combining WGS, RNA-seq, and IHC data with variant annotation from public databases.",
        ["translational"],
        (3, 5),
        ["Precision Oncology", "Clinical Genomics", "Translational Science"],
    ),
    (
        "Pharmacovigilance Warehouse",
        "Global adverse event aggregation from FDA FAERS, EMA EudraVigilance, and WHO VigiBase with MedDRA coding.",
        ["clinical"],
        (3, 5),
        ["Drug Safety", "Regulatory Affairs", "Pharmacovigilance"],
    ),
    (
        "Market Share Tracker",
        "Weekly prescription volume tracking across channels and geographies from multiple data vendors.",
        ["commercial"],
        (2, 4),
        ["Commercial Analytics", "Sales Operations", "Brand Teams"],
    ),
    (
        "Single-Cell Atlas",
        "Curated single-cell RNA-seq and spatial transcriptomics data for tissue-level gene expression profiling.",
        ["translational"],
        (2, 3),
        ["Computational Biology", "Translational Science", "Discovery Biology"],
    ),
    (
        "HCP Engagement Platform",
        "Integrated healthcare professional data combining engagement history, prescribing patterns, and KOL profiling.",
        ["commercial"],
        (2, 4),
        ["Medical Affairs", "Field Medical", "Commercial Operations"],
    ),
    (
        "Regulatory Submission Package",
        "Pre-assembled clinical data packages for regulatory submissions including safety, efficacy, and bioanalytical data.",
        ["clinical"],
        (3, 5),
        ["Regulatory Affairs", "Clinical Development", "Biostatistics"],
    ),
    (
        "Target Identification Suite",
        "Multi-modal target discovery combining CRISPR screens, protein structures, and interaction databases for novel target identification.",
        ["discovery"],
        (3, 5),
        ["Target Sciences", "Computational Biology", "Discovery Biology"],
    ),
    (
        "Fragment-Based Drug Design",
        "Fragment screening library data with structural biology and biophysical assay results for fragment-to-lead campaigns.",
        ["discovery"],
        (2, 3),
        ["Structural Biology", "Medicinal Chemistry", "Computational Chemistry"],
    ),
    (
        "Imaging Analytics Platform",
        "Integrated pathology and radiology imaging data with AI-derived features for disease characterization.",
        ["translational"],
        (2, 3),
        ["Digital Pathology", "Radiology", "Translational Science"],
    ),
    (
        "Clinical Biobank Inventory",
        "Sample tracking and biobank management data linking biospecimens to patient clinical data.",
        ["clinical"],
        (2, 3),
        ["Biobank Operations", "Translational Science", "Clinical Operations"],
    ),
    (
        "Launch Analytics Dashboard",
        "Market access, formulary status, and launch readiness metrics for commercial launch planning.",
        ["commercial"],
        (2, 3),
        ["Launch Team", "Market Access", "Commercial Strategy"],
    ),
]


def _scale_product_templates(templates: list, scale: int) -> list:
    """Expand product templates by scale factor."""
    if scale <= 1:
        return templates
    expanded = list(templates)
    region_suffixes = ["NA", "EMEA", "APAC", "LATAM", "Global"]
    for s in range(1, scale):
        for entry in templates:
            name, desc, dept_sources, n_range, consumers = entry
            suffix = region_suffixes[(s - 1 + hash(name)) % len(region_suffixes)]
            new_name = f"{name} — {suffix}"
            expanded.append((new_name, desc, dept_sources, n_range, consumers))
    return expanded


def generate_business_products(
    all_datasets: Dict[str, List[DatasetRecord]],
    contracts: List[ContractRecord],
    scale: int = 1,
) -> List[BusinessProduct]:
    products = []
    # Flatten datasets by department for easy lookup
    by_dept: Dict[str, List[DatasetRecord]] = {}
    for dept, ds_list in all_datasets.items():
        by_dept[dept] = ds_list

    # Build dataset_id → strictest contract classification
    classification_strength = {"restricted": 0, "confidential": 1, "internal": 2, "public": 3}
    ds_contract_class: Dict[str, str] = {}
    for ctr in contracts:
        for ds in ctr.covered_datasets:
            existing = ds_contract_class.get(ds["dataset_id"])
            if existing is None or classification_strength.get(ctr.classification, 99) < classification_strength.get(
                existing, 99
            ):
                ds_contract_class[ds["dataset_id"]] = ctr.classification

    dept_owners = {
        "discovery": OWNERS_DISCOVERY,
        "translational": OWNERS_TRANSLATIONAL,
        "clinical": OWNERS_CLINICAL,
        "commercial": OWNERS_COMMERCIAL,
    }

    limitations = [
        "Data completeness varies by site; some sites have >30-day reporting lag.",
        "External reference data refreshed quarterly; may not reflect latest releases.",
        "De-identification may exclude rare variants with low population frequency.",
        "Historical data prior to 2021 uses legacy schema and may have mapping gaps.",
        "Some assay results pending QC review and marked as provisional.",
        "Cross-vendor patient linkage is probabilistic with ~95% match rate.",
        "Imaging data limited to sites with compatible scanner hardware.",
        "Real-world evidence subject to selection bias inherent in claims data.",
    ]

    for i, (name, desc, dept_sources, n_range, consumers) in enumerate(
        _scale_product_templates(PRODUCT_TEMPLATES, scale), 1
    ):
        # Pick source datasets from the specified departments
        candidate_datasets = []
        for dept in dept_sources:
            candidate_datasets.extend(by_dept.get(dept, []))

        n_sources = min(random.randint(*n_range), len(candidate_datasets))
        selected = random.sample(candidate_datasets, n_sources)

        # Determine refresh as the fastest among sources
        cadence_order = {c: j for j, c in enumerate(CADENCES)}
        fastest_source = min(selected, key=lambda d: cadence_order.get(d.refresh_cadence, 99))

        # Inherit strictest classification from source datasets' contracts
        # If no external sources, default to "internal"
        strictest_class = "internal"
        for ds in selected:
            if ds.dataset_id in ds_contract_class:
                ctr_class = ds_contract_class[ds.dataset_id]
                if classification_strength.get(ctr_class, 99) < classification_strength.get(strictest_class, 99):
                    strictest_class = ctr_class

        # Compute retention: minimum retention across all contracts covering selected datasets
        # (most restrictive contract wins — can't keep data longer than any contract allows)
        ds_contract_retention: Dict[str, int] = {}
        for ctr in contracts:
            for cds in ctr.covered_datasets:
                existing = ds_contract_retention.get(cds["dataset_id"])
                if existing is None or ctr.retention_limit_days < existing:
                    ds_contract_retention[cds["dataset_id"]] = ctr.retention_limit_days
        min_retention = 0
        for ds in selected:
            if ds.dataset_id in ds_contract_retention:
                r = ds_contract_retention[ds.dataset_id]
                if min_retention == 0:
                    min_retention = r
                else:
                    min_retention = min(min_retention, r)

        primary_dept = dept_sources[0]
        products.append(
            BusinessProduct(
                product_id=_id("BP", i),
                name=name,
                owner=_pick(dept_owners[primary_dept]),
                classification=strictest_class,
                refresh_frequency=fastest_source.refresh_cadence,
                created_date=_date("2022-01-01", "2025-06-01"),
                description=desc,
                source_datasets=[
                    {
                        "dataset_id": ds.dataset_id,
                        "name": ds.name,
                        "domain": ds.department,
                        "source_type": ds.source_type,
                        "storage_path": ds.storage_path,
                        "table_name": ds.table_name,
                    }
                    for ds in selected
                ],
                retention_days=min_retention,
                completeness_pct=round(random.uniform(75.0, 99.5), 1),
                last_validated=_date("2025-01-01", "2025-12-31"),
                known_limitations=_pick(limitations),
                consumers=consumers,
                request_process=_pick(["self-serve", "approval-required", "restricted"]),
            )
        )

    return products


# ── writers ──────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "dataset_id",
    "name",
    "storage_path",
    "table_name",
    "schema_columns",
    "format",
    "refresh_cadence",
    "source_type",
    "provider",
    "owner",
    "created_date",
    "row_count",
]


def write_technical_catalogs(all_datasets: Dict[str, List[DatasetRecord]]):
    out = RESOURCES / "technical_catalog"
    for dept, records in all_datasets.items():
        path = out / f"{dept}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            w.writeheader()
            for r in records:
                row = {k: getattr(r, k) for k in CSV_COLUMNS}
                w.writerow(row)


def write_contracts(contracts: List[ContractRecord]):
    out = RESOURCES / "contracts"
    for ctr in contracts:
        path = out / f"{_slug(ctr.provider)}.md"
        covered_table = "\n".join(
            f"| {d['dataset_id']} | {d['name']} | {d['permitted_use']} |" for d in ctr.covered_datasets
        )
        content = f"""# Data Sharing Agreement: {ctr.provider}

- **Contract ID**: {ctr.contract_id}
- **Provider**: {ctr.provider}
- **Effective Date**: {ctr.effective_date}
- **Expiry Date**: {ctr.expiry_date}
- **Status**: {ctr.status}

## Covered Datasets

| dataset_id | name | permitted_use |
|---|---|---|
{covered_table}

## Terms

- **Refresh SLA**: {ctr.refresh_sla}
- **Retention Limit**: {ctr.retention_limit_days} days
- **Data Classification**: {ctr.classification}
- **Geographic Restriction**: {ctr.geo_restriction}
- **De-identification Required**: {"yes" if ctr.deidentification_required else "no"}
- **Audit Rights**: {ctr.audit_rights}
"""
        path.write_text(content)


def write_business_products(products: List[BusinessProduct]):
    out = RESOURCES / "business_catalog"
    for bp in products:
        path = out / f"{_slug(bp.name)}.md"
        source_table = "\n".join(
            f"| {s['dataset_id']} | {s['name']} | {s['domain']} | {s['source_type']} | {s['storage_path']} | {s['table_name']} |"
            for s in bp.source_datasets
        )
        consumers_str = ", ".join(bp.consumers)
        retention_line = (
            f"- **Data Retention**: {bp.retention_days} days"
            if bp.retention_days > 0
            else "- **Data Retention**: unlimited (internal only)"
        )
        content = f"""# Data Product: {bp.name}

- **Product ID**: {bp.product_id}
- **Owner**: {bp.owner}
- **Classification**: {bp.classification}
- **Refresh Frequency**: {bp.refresh_frequency}
- **Created**: {bp.created_date}
{retention_line}

## Description

{bp.description}

## Source Datasets

| dataset_id | name | domain | source_type | storage_path | table_name |
|---|---|---|---|---|---|
{source_table}

## Data Quality

- **Completeness**: {bp.completeness_pct}%
- **Last Validated**: {bp.last_validated}
- **Known Limitations**: {bp.known_limitations}

## Access

- **Consumers**: {consumers_str}
- **Request Process**: {bp.request_process}
"""
        path.write_text(content)


# ── .pltg generation ─────────────────────────────────────────────────

SRC = Path(__file__).parent / "src"


def _pltg_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write_pltg_load_contracts(contracts: List[ContractRecord]):
    """Generate src/load_contracts.pltg — load-document for each contract."""
    lines = ["; Auto-generated: load contract documents"]
    for ctr in contracts:
        slug = _slug(ctr.provider)
        filepath = RESOURCES / "contracts" / f"{slug}.md"
        if filepath.exists():
            lines.append(f'(load-document "contract:{slug}" "../resources/contracts/{slug}.md")')
    (SRC / "load_contracts.pltg").write_text("\n".join(lines) + "\n")


def write_pltg_load_business(products: List[BusinessProduct]):
    """Generate src/load_business.pltg — load-document for each product."""
    lines = ["; Auto-generated: load business catalog documents"]
    for bp in products:
        slug = _slug(bp.name)
        lines.append(f'(load-document "business:{slug}" "../resources/business_catalog/{slug}.md")')
    (SRC / "load_business.pltg").write_text("\n".join(lines) + "\n")


def write_pltg_load_technical(all_datasets: Dict[str, List[DatasetRecord]]):
    """Generate src/load_technical.pltg — load-document for each tech CSV."""
    lines = ["; Auto-generated: load technical catalog CSV documents"]
    for dept in sorted(all_datasets.keys()):
        lines.append(f'(load-document "tech:{dept}" "../resources/technical_catalog/{dept}.csv")')
    (SRC / "load_technical.pltg").write_text("\n".join(lines) + "\n")


def write_pltg_technical(all_datasets: Dict[str, List[DatasetRecord]]):
    """Generate src/technical.pltg — facts from technical catalog CSVs."""
    lines = ["; Auto-generated: technical catalog facts"]
    for dept, records in sorted(all_datasets.items()):
        doc_name = f"tech:{dept}"
        lines.append(f"\n; --- {dept} ---")
        for ds in records:
            safe = ds.dataset_id.lower().replace("-", "_")
            lines.extend(
                [
                    f'(fact {safe}-path "{_pltg_escape(ds.storage_path)}"',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{_pltg_escape(ds.storage_path)}")',
                    f'    :explanation "Storage path for {_pltg_escape(ds.name)}"))',
                    "",
                    f'(fact {safe}-table "{_pltg_escape(ds.table_name)}"',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{_pltg_escape(ds.table_name)}")',
                    f'    :explanation "Table name for {_pltg_escape(ds.name)}"))',
                    "",
                    f'(fact {safe}-cadence "{ds.refresh_cadence}"',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{ds.refresh_cadence}")',
                    f'    :explanation "Refresh cadence for {_pltg_escape(ds.name)}"))',
                    "",
                    f'(fact {safe}-source-type "{ds.source_type}"',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{ds.source_type}")',
                    f'    :explanation "Source type for {_pltg_escape(ds.name)}"))',
                    "",
                    f'(fact {safe}-owner "{_pltg_escape(ds.owner)}"',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{_pltg_escape(ds.owner)}")',
                    f'    :explanation "Owner of {_pltg_escape(ds.name)}"))',
                    "",
                ]
            )
    (SRC / "technical.pltg").write_text("\n".join(lines) + "\n")


def write_pltg_contracts(contracts: List[ContractRecord]):
    """Generate src/contracts.pltg — facts from contract .md files."""
    lines = ["; Auto-generated: contract facts"]
    for ctr in contracts:
        slug = _slug(ctr.provider)
        filepath = RESOURCES / "contracts" / f"{slug}.md"
        if not filepath.exists():
            continue
        safe = slug.replace("-", "_")
        doc_name = f"contract:{slug}"

        lines.extend(
            [
                f"\n; --- {ctr.provider} ---",
                f'(fact ctr-{safe}-sla "{ctr.refresh_sla}"',
                f'  :evidence (evidence "{doc_name}"',
                f'    :quotes ("{ctr.refresh_sla}")',
                f'    :explanation "Refresh SLA for {_pltg_escape(ctr.provider)} contract"))',
                "",
                f'(fact ctr-{safe}-retention "{ctr.retention_limit_days} days"',
                f'  :evidence (evidence "{doc_name}"',
                f'    :quotes ("{ctr.retention_limit_days} days")',
                f'    :explanation "Retention limit for {_pltg_escape(ctr.provider)} contract"))',
                "",
                f'(fact ctr-{safe}-classification "{ctr.classification}"',
                f'  :evidence (evidence "{doc_name}"',
                f'    :quotes ("{ctr.classification}")',
                f'    :explanation "Data classification for {_pltg_escape(ctr.provider)} contract"))',
                "",
                f'(fact ctr-{safe}-expiry "{ctr.expiry_date}"',
                f'  :evidence (evidence "{doc_name}"',
                f'    :quotes ("{ctr.expiry_date}")',
                f'    :explanation "Expiry date for {_pltg_escape(ctr.provider)} contract"))',
                "",
                f'(fact ctr-{safe}-status "{ctr.status}"',
                f'  :evidence (evidence "{doc_name}"',
                f'    :quotes ("{ctr.status}")',
                f'    :explanation "Contract status for {_pltg_escape(ctr.provider)}"))',
                "",
            ]
        )

        for ds in ctr.covered_datasets:
            ds_safe = ds["dataset_id"].lower().replace("-", "_")
            lines.extend(
                [
                    f'(fact ctr-{safe}-covers-{ds_safe} true',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{_pltg_escape(ds["dataset_id"])}")',
                    f'    :explanation "{_pltg_escape(ctr.provider)} contract covers {_pltg_escape(ds["name"])}"))',
                    "",
                    f'(fact ctr-{safe}-use-{ds_safe} "{ds["permitted_use"]}"',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{_pltg_escape(ds["permitted_use"])}")',
                    f'    :explanation "Permitted use for {_pltg_escape(ds["name"])} under {_pltg_escape(ctr.provider)}"))',
                    "",
                ]
            )

    (SRC / "contracts.pltg").write_text("\n".join(lines) + "\n")


def write_pltg_business(products: List[BusinessProduct]):
    """Generate src/business.pltg — facts from business catalog .md files."""
    lines = ["; Auto-generated: business catalog facts"]
    for bp in products:
        slug = _slug(bp.name)
        safe = slug.replace("-", "_")
        doc_name = f"business:{slug}"

        lines.extend(
            [
                f"\n; --- {bp.name} ---",
                f'(fact bp-{safe}-owner "{_pltg_escape(bp.owner)}"',
                f'  :evidence (evidence "{doc_name}"',
                f'    :quotes ("{_pltg_escape(bp.owner)}")',
                f'    :explanation "Owner of {_pltg_escape(bp.name)}"))',
                "",
                f'(fact bp-{safe}-classification "{bp.classification}"',
                f'  :evidence (evidence "{doc_name}"',
                f'    :quotes ("{bp.classification}")',
                f'    :explanation "Classification of {_pltg_escape(bp.name)}"))',
                "",
                f'(fact bp-{safe}-refresh "{bp.refresh_frequency}"',
                f'  :evidence (evidence "{doc_name}"',
                f'    :quotes ("{bp.refresh_frequency}")',
                f'    :explanation "Refresh frequency of {_pltg_escape(bp.name)}"))',
                "",
            ]
        )

        if bp.retention_days > 0:
            lines.extend(
                [
                    f'(fact bp-{safe}-retention {bp.retention_days}',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{bp.retention_days} days")',
                    f'    :explanation "Data retention for {_pltg_escape(bp.name)}"))',
                    "",
                ]
            )

        for src in bp.source_datasets:
            ds_safe = src["dataset_id"].lower().replace("-", "_")
            lines.extend(
                [
                    f'(fact bp-{safe}-uses-{ds_safe} true',
                    f'  :evidence (evidence "{doc_name}"',
                    f'    :quotes ("{_pltg_escape(src["dataset_id"])}")',
                    f'    :explanation "{_pltg_escape(bp.name)} uses {_pltg_escape(src["name"])}"))',
                    "",
                ]
            )

    (SRC / "business.pltg").write_text("\n".join(lines) + "\n")


def write_pltg_manifest():
    """Generate src/manifest.pltg — aggregated imports of all generated fact modules.

    Scans for all generated .pltg files (which may be scattered across
    subdirectories) and emits a single manifest that imports them all.
    The checker imports manifest once and gets every fact available.
    """
    skip = {"manifest"}
    lines = [
        "; Auto-generated: aggregated fact imports",
        "; Collects all generated .pltg modules — do not hand-edit",
        "",
    ]

    # Collect all modules, but load documents (load_*) before facts
    # so that evidence verification can find the document text.
    load_modules = []
    fact_modules = []
    for pltg_file in sorted(SRC.rglob("*.pltg")):
        if pltg_file.stem in skip:
            continue
        rel = pltg_file.relative_to(SRC).with_suffix("")
        module_path = str(rel).replace("/", ".")
        if pltg_file.stem.startswith("load_"):
            load_modules.append(module_path)
        else:
            fact_modules.append(module_path)
    for mod in load_modules + fact_modules:
        lines.append(f'(import (quote {mod}))')

    (SRC / "manifest.pltg").write_text("\n".join(lines) + "\n")


def write_all_pltg(
    all_datasets: Dict[str, List[DatasetRecord]],
    contracts: List[ContractRecord],
    products: List[BusinessProduct],
):
    """Write all generated .pltg files."""
    SRC.mkdir(parents=True, exist_ok=True)
    write_pltg_load_contracts(contracts)
    write_pltg_load_business(products)
    write_pltg_load_technical(all_datasets)
    write_pltg_technical(all_datasets)
    write_pltg_contracts(contracts)
    write_pltg_business(products)
    write_pltg_manifest()


# ── phase 2: inject inconsistencies ─────────────────────────────────


@dataclass
class Corruption:
    corruption_type: str
    layer: str
    file: str
    field: str
    old_value: str
    new_value: str
    description: str


def inject_inconsistencies(
    all_datasets: Dict[str, List[DatasetRecord]],
    contracts: List[ContractRecord],
    products: List[BusinessProduct],
    scale: int = 1,
) -> List[Corruption]:
    corruptions: List[Corruption] = []

    def _n(base: int, pool_size: int) -> int:
        """Scale corruption count proportionally, capped by pool size."""
        return min(base * scale, pool_size)

    # Flatten all datasets
    flat_datasets = [ds for dept in all_datasets.values() for ds in dept]
    _external_datasets = [ds for ds in flat_datasets if ds.source_type == "external"]

    # Datasets reachable from business products — only corrupt what we can detect
    reachable_ds_ids = {src["dataset_id"] for bp in products for src in bp.source_datasets}
    reachable_datasets = [ds for ds in flat_datasets if ds.dataset_id in reachable_ds_ids]
    reachable_contracts = [
        c for c in contracts if any(ds["dataset_id"] in reachable_ds_ids for ds in c.covered_datasets)
    ]

    # ── 1. Path drift (technical layer) ──
    victims = random.sample(reachable_datasets, _n(5, len(reachable_datasets)))
    for ds in victims:
        old_path = ds.storage_path
        new_path = old_path.replace("s3://", "s3://migrated-")
        corruptions.append(
            Corruption(
                "path_drift",
                "technical",
                f"{ds.department}.csv",
                "storage_path",
                old_path,
                new_path,
                f"Storage path migrated for {ds.name}",
            )
        )
        _mutate_csv(ds.department, ds.dataset_id, "storage_path", new_path)

    # ── 2. Table rename (technical layer) ──
    victims = random.sample(reachable_datasets, _n(3, len(reachable_datasets)))
    for ds in victims:
        old_table = ds.table_name
        new_table = old_table + "_v2"
        corruptions.append(
            Corruption(
                "table_rename",
                "technical",
                f"{ds.department}.csv",
                "table_name",
                old_table,
                new_table,
                f"Table renamed for {ds.name}",
            )
        )
        _mutate_csv(ds.department, ds.dataset_id, "table_name", new_table)

    # ── 3. Cadence change (technical layer) ──
    victims = random.sample(reachable_datasets, _n(4, len(reachable_datasets)))
    for ds in victims:
        old_cadence = ds.refresh_cadence
        new_cadence = _pick([c for c in CADENCES if c != old_cadence])
        corruptions.append(
            Corruption(
                "cadence_mismatch",
                "technical",
                f"{ds.department}.csv",
                "refresh_cadence",
                old_cadence,
                new_cadence,
                f"Refresh cadence changed for {ds.name}",
            )
        )
        _mutate_csv(ds.department, ds.dataset_id, "refresh_cadence", new_cadence)

    # ── 4. Contract gap (delete contract for external dataset) ──
    if len(contracts) >= 3:
        victim_contracts = random.sample(contracts, _n(2, len(contracts)))
        for ctr in victim_contracts:
            filepath = RESOURCES / "contracts" / f"{_slug(ctr.provider)}.md"
            if filepath.exists():
                filepath.unlink()
                corruptions.append(
                    Corruption(
                        "contract_gap",
                        "contracts",
                        f"{_slug(ctr.provider)}.md",
                        "file",
                        "exists",
                        "deleted",
                        f"Contract deleted for provider {ctr.provider} covering {len(ctr.covered_datasets)} datasets",
                    )
                )

    # ── 5. SLA mismatch (contract layer) ──
    modifiable = [c for c in reachable_contracts if (RESOURCES / "contracts" / f"{_slug(c.provider)}.md").exists()]
    if len(modifiable) >= 3:
        victims = random.sample(modifiable, _n(3, len(modifiable)))
        for ctr in victims:
            old_sla = ctr.refresh_sla
            new_sla = _pick([c for c in CADENCES if c != old_sla])
            corruptions.append(
                Corruption(
                    "sla_mismatch",
                    "contracts",
                    f"{_slug(ctr.provider)}.md",
                    "refresh_sla",
                    old_sla,
                    new_sla,
                    f"Contract SLA changed for {ctr.provider}",
                )
            )
            _mutate_contract_field(ctr.provider, "Refresh SLA", new_sla)

    # ── 6. Retention conflict (contract layer) ──
    if len(modifiable) >= 2:
        victims = random.sample(modifiable, _n(2, len(modifiable)))
        for ctr in victims:
            old_ret = str(ctr.retention_limit_days)
            new_ret = str(_pick([30, 60]))  # very short
            corruptions.append(
                Corruption(
                    "retention_conflict",
                    "contracts",
                    f"{_slug(ctr.provider)}.md",
                    "retention_limit",
                    f"{old_ret} days",
                    f"{new_ret} days",
                    f"Retention limit shortened for {ctr.provider}",
                )
            )
            _mutate_contract_field(ctr.provider, "Retention Limit", f"{new_ret} days")

    # ── 7. Expired contract (contract layer) ──
    if len(modifiable) >= 2:
        victims = random.sample(modifiable, _n(2, len(modifiable)))
        for ctr in victims:
            old_expiry = ctr.expiry_date
            new_expiry = _past_date()
            corruptions.append(
                Corruption(
                    "expired_contract",
                    "contracts",
                    f"{_slug(ctr.provider)}.md",
                    "expiry_date",
                    old_expiry,
                    new_expiry,
                    f"Contract expiry backdated for {ctr.provider}",
                )
            )
            _mutate_contract_field(ctr.provider, "Expiry Date", new_expiry)
            _mutate_contract_field(ctr.provider, "Status", "expired")

    # ── 8. Phantom reference (business layer) ──
    victims = random.sample(products, _n(4, len(products)))
    for bp in victims:
        if bp.source_datasets:
            phantom_id = _id("DS", random.randint(9900, 9999))
            phantom_entry = {
                "dataset_id": phantom_id,
                "name": f"Phantom Dataset {phantom_id}",
                "domain": "unknown",
                "source_type": "internal",
                "storage_path": f"s3://phantom-lake/{phantom_id.lower()}",
                "table_name": f"phantom_{phantom_id.lower().replace('-', '_')}",
            }
            corruptions.append(
                Corruption(
                    "phantom_reference",
                    "business",
                    f"{_slug(bp.name)}.md",
                    "source_datasets",
                    "none",
                    phantom_id,
                    f"Added phantom dataset reference to {bp.name}",
                )
            )
            _add_phantom_source(bp.name, phantom_entry)

    # ── 9. Owner drift (business layer) ──
    victims = random.sample(products, _n(3, len(products)))
    for bp in victims:
        old_owner = bp.owner
        all_owners = OWNERS_DISCOVERY + OWNERS_TRANSLATIONAL + OWNERS_CLINICAL + OWNERS_COMMERCIAL
        new_owner = _pick([o for o in all_owners if o != old_owner])
        corruptions.append(
            Corruption(
                "owner_drift",
                "business",
                f"{_slug(bp.name)}.md",
                "owner",
                old_owner,
                new_owner,
                f"Owner changed for {bp.name}",
            )
        )
        _mutate_business_field(bp.name, "Owner", new_owner)

    # ── 10. Classification conflict (business layer) ──
    victims = random.sample(products, _n(3, len(products)))
    for bp in victims:
        old_class = bp.classification
        # Set to "public" — likely conflicts with restricted/confidential contracts
        new_class = "public" if old_class != "public" else "internal"
        corruptions.append(
            Corruption(
                "classification_conflict",
                "business",
                f"{_slug(bp.name)}.md",
                "classification",
                old_class,
                new_class,
                f"Classification weakened for {bp.name}",
            )
        )
        _mutate_business_field(bp.name, "Classification", new_class)

    # ── 11. Omics classification weakened (contract layer) ──
    # Contracts covering omics data must be "restricted" — weaken to "confidential"
    omics_contracts = [
        c
        for c in modifiable
        if c.classification == "restricted"
        and any(
            re.search(r"(?i)genom|proteom|transcriptom|omics|crispr|rna.seq|wgs", ds["name"])
            for ds in c.covered_datasets
        )
    ]
    for ctr in random.sample(omics_contracts, _n(2, len(omics_contracts))):
        corruptions.append(
            Corruption(
                "omics_classification_weakened",
                "contracts",
                f"{_slug(ctr.provider)}.md",
                "classification",
                "restricted",
                "confidential",
                f"Omics contract classification weakened for {ctr.provider}",
            )
        )
        _mutate_contract_field(ctr.provider, "Data Classification", "confidential")

    # ── 12. Refresh mismatch (business layer) ──
    victims = random.sample(products, _n(3, len(products)))
    for bp in victims:
        old_freq = bp.refresh_frequency
        new_freq = _pick([c for c in CADENCES if c != old_freq])
        corruptions.append(
            Corruption(
                "refresh_mismatch",
                "business",
                f"{_slug(bp.name)}.md",
                "refresh_frequency",
                old_freq,
                new_freq,
                f"Refresh frequency changed for {bp.name}",
            )
        )
        _mutate_business_field(bp.name, "Refresh Frequency", new_freq)

    return corruptions


# ── mutation helpers ─────────────────────────────────────────────────


def _mutate_csv(department: str, dataset_id: str, field: str, new_value: str):
    path = RESOURCES / "technical_catalog" / f"{department}.csv"
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["dataset_id"] == dataset_id:
                row[field] = new_value
            rows.append(row)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _mutate_contract_field(provider: str, field_label: str, new_value: str):
    path = RESOURCES / "contracts" / f"{_slug(provider)}.md"
    if not path.exists():
        return
    text = path.read_text()
    import re

    text = re.sub(
        rf"(\*\*{re.escape(field_label)}\*\*): .+",
        rf"\1: {new_value}",
        text,
    )
    path.write_text(text)


def _mutate_business_field(product_name: str, field_label: str, new_value: str):
    path = RESOURCES / "business_catalog" / f"{_slug(product_name)}.md"
    if not path.exists():
        return
    text = path.read_text()
    import re

    text = re.sub(
        rf"(\*\*{re.escape(field_label)}\*\*): .+",
        rf"\1: {new_value}",
        text,
    )
    path.write_text(text)


def _add_phantom_source(product_name: str, phantom: dict):
    path = RESOURCES / "business_catalog" / f"{_slug(product_name)}.md"
    if not path.exists():
        return
    text = path.read_text()
    # Add a row to the source datasets table
    new_row = f"| {phantom['dataset_id']} | {phantom['name']} | {phantom['domain']} | {phantom['source_type']} | {phantom['storage_path']} | {phantom['table_name']} |"
    # Insert before the "## Data Quality" section
    text = text.replace("## Data Quality", f"{new_row}\n\n## Data Quality")
    path.write_text(text)


# ── main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic data governance demo data")
    parser.add_argument("--clean", action="store_true", help="Wipe and regenerate resources/")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed")
    parser.add_argument("--scale", type=int, default=1, help="Scale factor (1=~68 datasets, 5=~340, 10=~680)")
    parser.add_argument(
        "--consistent-only", action="store_true", help="Generate only the consistent baseline (no corruptions)"
    )
    args = parser.parse_args()

    random.seed(args.seed)
    _seen_ids.clear()

    if args.clean:
        for sub in ["technical_catalog", "contracts", "business_catalog"]:
            d = RESOURCES / sub
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
    else:
        for sub in ["technical_catalog", "contracts", "business_catalog"]:
            (RESOURCES / sub).mkdir(parents=True, exist_ok=True)

    # Phase 1: consistent baseline
    print("Phase 1: Generating consistent baseline...")
    all_datasets = generate_all_datasets(scale=args.scale)
    total_ds = sum(len(v) for v in all_datasets.values())
    write_technical_catalogs(all_datasets)
    print(f"  Technical catalog: {total_ds} datasets across {len(all_datasets)} CSVs")

    contracts = generate_contracts(all_datasets)
    write_contracts(contracts)
    print(f"  Contracts: {len(contracts)} agreements")

    products = generate_business_products(all_datasets, contracts, scale=args.scale)
    write_business_products(products)
    print(f"  Business catalog: {len(products)} data products")

    write_all_pltg(all_datasets, contracts, products)
    print("  Generated .pltg modules in src/")

    if args.consistent_only:
        print("\nDone (consistent baseline only, no corruptions).")
        return

    # Phase 2: inject inconsistencies
    print("\nPhase 2: Injecting inconsistencies...")
    corruptions = inject_inconsistencies(all_datasets, contracts, products, scale=args.scale)

    # Re-generate .pltg after corruptions (reads mutated files)
    write_all_pltg(all_datasets, contracts, products)

    # Write manifest
    manifest = {
        "seed": args.seed,
        "total_datasets": total_ds,
        "total_contracts": len(contracts),
        "total_products": len(products),
        "corruptions": [asdict(c) for c in corruptions],
        "corruption_summary": {},
    }
    for c in corruptions:
        manifest["corruption_summary"][c.corruption_type] = manifest["corruption_summary"].get(c.corruption_type, 0) + 1

    manifest_path = Path(__file__).parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"  Injected {len(corruptions)} corruptions:")
    for ctype, count in sorted(manifest["corruption_summary"].items()):
        print(f"    {ctype}: {count}")
    print(f"\n  Manifest written to {manifest_path}")
    print("Done.")


if __name__ == "__main__":
    main()
