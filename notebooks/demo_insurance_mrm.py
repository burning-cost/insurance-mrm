# Databricks notebook source
# COMMAND ----------

# MAGIC %md
# MAGIC # insurance-mrm: Full Workflow Demo
# MAGIC
# MAGIC This notebook demonstrates the complete insurance-mrm governance workflow
# MAGIC on a realistic UK motor insurance pricing model scenario.
# MAGIC
# MAGIC **Scenario:** A mid-tier UK insurer has just run their annual validation of the
# MAGIC Motor TPPD Frequency CatBoost model. The Model Risk Committee meeting is in
# MAGIC two weeks. We need to:
# MAGIC
# MAGIC 1. Build the model card with assumptions register and monitoring plan
# MAGIC 2. Score the risk tier (and show the rationale)
# MAGIC 3. Register the model in the inventory alongside other models
# MAGIC 4. Query the inventory to prepare the MRC agenda
# MAGIC 5. Generate the executive committee governance pack (HTML)

# COMMAND ----------

import subprocess, sys, shutil, os

# Copy from workspace to /tmp so __pycache__ can be written
dst = "/tmp/insurance-mrm-demo"
if os.path.exists(dst):
    shutil.rmtree(dst)
shutil.copytree("/Workspace/insurance-mrm", dst,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))

result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-e", dst, "--quiet"],
    capture_output=True, text=True,
)
if result.returncode != 0:
    print("INSTALL FAILED:", result.stderr[:2000])
else:
    print("Install OK")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Model card
# MAGIC
# MAGIC The model card captures everything a governance committee needs to
# MAGIC understand the model, its limitations, and who is responsible for it.

# COMMAND ----------

from insurance_mrm import (
    ModelCard, Assumption, Limitation,
    ModelInventory, RiskTierScorer, GovernanceReport,
)

motor_card = ModelCard(
    model_id='motor-freq-tppd-v2',
    model_name='Motor TPPD Frequency',
    version='2.1.0',
    model_class='pricing',
    intended_use=(
        'Frequency pricing for private motor third-party property damage. '
        'Used as the frequency component in a Tweedie pure premium model. '
        'In production for policies renewing from January 2025.'
    ),
    not_intended_for=[
        'Commercial motor',
        'Fleet policies',
        'Reserving (separate IBNR model applies)',
        'Regulatory capital (Solvency II internal model uses separate approved model)',
    ],
    target_variable='claim_count',
    distribution_family='Poisson',
    model_type='CatBoost',
    rating_factors=[
        'driver_age', 'driver_experience_years', 'vehicle_age',
        'vehicle_group_abi', 'annual_mileage_band', 'region',
        'occupation_class', 'no_claims_discount',
    ],
    training_data_period=('2019-01-01', '2023-12-31'),
    development_date='2024-09-01',
    developer='Pricing Analytics Team',
    champion_challenger_status='champion',
    portfolio_scope='Private motor, new business and renewal',
    geographic_scope='UK personal lines (England, Wales, Scotland)',
    gwp_impacted=125_000_000,
    customer_facing=True,
    regulatory_use=False,
    assumptions=[
        Assumption(
            description='Claim frequency distribution is stationary since 2022',
            risk='MEDIUM',
            mitigation='Quarterly A/E monitoring by underwriting year. '
                       'PSI alert threshold set at 0.25.',
            rationale='Disruption from COVID and subsequent driving pattern changes '
                      'make stationarity uncertain pre-2022. 2022-2023 data used '
                      'for OOT validation showed Gini within 0.02 of in-sample.',
        ),
        Assumption(
            description='ABI Vehicle Group adequately proxies repair cost risk',
            risk='LOW',
            mitigation='ABI cross-reference checked at annual model review.',
        ),
        Assumption(
            description='Self-reported annual mileage is reliable',
            risk='MEDIUM',
            mitigation='Telematics pilot data cross-check scheduled Q2 2026. '
                       'Mileage bands used (not exact figures) to reduce impact '
                       'of misreporting.',
        ),
        Assumption(
            description='No structural break from electric vehicle adoption',
            risk='HIGH',
            mitigation='EV segment monitored separately (volume too thin for '
                       'separate model). Review if EV share exceeds 15% of book.',
        ),
        Assumption(
            description='Regional effects are stable over the model lifetime',
            risk='LOW',
            mitigation='PSI on region feature monitored quarterly.',
        ),
    ],
    limitations=[
        Limitation(
            description='Thin training data for vehicles over 10 years old',
            impact='Prediction variance is materially higher for this segment; '
                   'model may over-smooth.',
            population_at_risk='~8% of current book',
            monitoring_flag=True,
        ),
        Limitation(
            description='No telematics integration',
            impact='High-mileage risk not fully captured; self-reported mileage '
                   'subject to adverse selection.',
            population_at_risk='Drivers reporting >15,000 miles annually',
            monitoring_flag=False,
        ),
        Limitation(
            description='Driver interactions (age x experience) modelled via '
                        'gradient boosting; not directly interpretable',
            impact='Difficult to explain individual predictions to customers '
                   'under FCA Consumer Duty if challenged.',
            population_at_risk='All customers',
            monitoring_flag=False,
        ),
    ],
    outstanding_issues=[
        'VIF check on driver_age x driver_experience_years interaction pending '
        '(scheduled for January 2026 validation update)',
    ],
    approved_by=['Chief Actuary', 'Model Risk Committee'],
    approval_date='2024-10-15',
    approval_conditions=(
        'Approved subject to: (1) quarterly A/E monitoring by Motor Pricing Team, '
        '(2) EV segment review if share exceeds 15%, '
        '(3) outstanding VIF check to be completed by end Q1 2026.'
    ),
    next_review_date='2025-10-15',
    monitoring_owner='Sarah Ahmed, Head of Pricing Analytics',
    monitoring_frequency='Quarterly',
    monitoring_triggers={
        'psi_score': 0.25,
        'ae_ratio_deviation': 0.10,
        'gini_drop_pct': 0.05,
    },
    trigger_actions={
        'psi_score': 'Escalate to Chief Actuary; consider ad-hoc refit review',
        'ae_ratio_deviation': 'Recalibration review within 30 days',
        'gini_drop_pct': 'Independent Gini stability test; report to MRC',
    },
    last_monitoring_run='2025-09-30',
    last_validation_run='2024-10-01',
    last_validation_run_id='run-abc-123-def',
    overall_rag='GREEN',
    materiality_tier=1,
)

print(f"Model card created: {motor_card.model_id}")
print(f"Assumptions: {len(motor_card.assumptions)} total, "
      f"{len(motor_card.high_risk_assumptions)} HIGH, "
      f"{len(motor_card.medium_risk_assumptions)} MEDIUM")
print(f"Approved: {motor_card.is_approved}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Risk tier scoring
# MAGIC
# MAGIC The scorer produces a 0-100 composite score across 6 dimensions.
# MAGIC The result includes a verbose rationale string suitable for MRC presentation.

# COMMAND ----------

scorer = RiskTierScorer()

tier = scorer.score(
    gwp_impacted=125_000_000,
    model_complexity='high',       # CatBoost with 8 features, trained on 4M rows
    deployment_status='champion',
    regulatory_use=False,
    external_data=False,
    customer_facing=True,
    validation_months_ago=12.0,    # Last validated October 2024; now October 2025
    drift_triggers_last_year=0,    # Clean monitoring record
)

print(f"Tier: {tier.tier} ({tier.tier_label})")
print(f"Score: {tier.score:.1f}/100")
print(f"Review frequency: {tier.review_frequency}")
print(f"Sign-off required: {tier.sign_off_requirement}")
print()
print("RATIONALE:")
print(tier.rationale)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Dimension breakdown

# COMMAND ----------

print(f"{'Dimension':<25} {'Contrib':>8} {'%':>6}  Rationale")
print("-" * 80)
for dim in tier.dimensions:
    weight = tier.weights_used[dim.name]
    contribution = (dim.score / dim.max_score) * weight
    print(f"{dim.name:<25} {contribution:>7.1f}  {dim.pct:>5.1f}%  {dim.rationale}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Model inventory
# MAGIC
# MAGIC We register multiple models to show the inventory query capabilities.

# COMMAND ----------

import tempfile

# Use a temp file for this demo
registry_path = os.path.join(tempfile.mkdtemp(), 'mrm_registry.json')
inventory = ModelInventory(registry_path)

# Register the motor model
inventory.register(motor_card, tier)

# Add a home buildings model
home_card = ModelCard(
    model_id='home-buildings-sev-v1',
    model_name='Home Buildings Severity',
    version='1.0.0',
    model_class='pricing',
    intended_use='Severity pricing for home buildings claims',
    champion_challenger_status='champion',
    gwp_impacted=45_000_000,
    customer_facing=True,
    approved_by=['Chief Actuary'],
    approval_date='2024-06-01',
    next_review_date='2026-01-01',
    monitoring_owner='James Brown',
    monitoring_frequency='Quarterly',
    overall_rag='AMBER',
)
home_tier = scorer.score(
    gwp_impacted=45_000_000,
    model_complexity='medium',
    deployment_status='champion',
    regulatory_use=False,
    external_data=False,
    customer_facing=True,
    validation_months_ago=16.0,
)
inventory.register(home_card, home_tier)

# Add a development model
fleet_card = ModelCard(
    model_id='fleet-freq-research-v0',
    model_name='Fleet Frequency Research Model',
    version='0.1.0',
    model_class='pricing',
    intended_use='Research prototype for commercial fleet pricing',
    champion_challenger_status='development',
    gwp_impacted=0.0,
    customer_facing=False,
    developer='Pricing Analytics Team',
)
inventory.register(fleet_card)

print(f"Registered {len(inventory.list())} models")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Inventory summary

# COMMAND ----------

summary = inventory.summary()
print(f"Total models: {summary['total_models']}")
print(f"By tier: {summary['by_tier']}")
print(f"By status: {summary['by_status']}")
print(f"By RAG: {summary['by_rag']}")
print(f"Overdue for review: {summary['overdue_count']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Query the inventory

# COMMAND ----------

# All champion models
champions = inventory.list(status='champion')
print("Champion models:")
for m in champions:
    print(f"  {m['model_name']} | Tier {m['materiality_tier']} | "
          f"RAG: {m['overall_rag']} | Next review: {m['next_review_date']}")

# COMMAND ----------

# Models due for review in the next 90 days
from datetime import date, timedelta

# Set a near-future review date to demonstrate the query
inventory.update_validation(
    model_id='home-buildings-sev-v1',
    validation_date='2025-09-01',
    overall_rag='AMBER',
    next_review_date=(date.today() + timedelta(days=45)).isoformat(),
    notes='Severity spike in South East region — recalibration under review',
)

due = inventory.due_for_review(within_days=90)
print(f"\nModels due for review within 90 days: {len(due)}")
for m in due:
    print(f"  {m['model_name']} — due {m['next_review_date']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Audit log

# COMMAND ----------

inventory.log_event(
    model_id='home-buildings-sev-v1',
    event_type='monitoring_trigger',
    description='A/E ratio reached 1.12 in South East region — exceeded 1.10 threshold',
    triggered_by='insurance-monitoring quarterly run 2025-Q3',
)

events = inventory.events(model_id='home-buildings-sev-v1')
print(f"Audit events for home-buildings-sev-v1: {len(events)}")
for evt in events:
    print(f"  [{evt['event_type']}] {evt['description']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Governance report
# MAGIC
# MAGIC Generate the executive committee pack for the MRC agenda.

# COMMAND ----------

report = GovernanceReport(
    card=motor_card,
    tier=tier,
    validation_results={
        'overall_rag': 'GREEN',
        'run_id': 'run-abc-123-def',
        'run_date': '2024-10-01',
        'gini': 0.42,
        'ae_ratio': 1.01,
        'psi_score': 0.07,
        'hl_p_value': 0.15,
        'section_results': [
            {'section': 'Data Quality', 'status': 'GREEN', 'notes': 'All checks passed'},
            {'section': 'Discrimination', 'status': 'GREEN', 'notes': 'Gini 0.42 (prev. 0.41)'},
            {'section': 'Calibration', 'status': 'GREEN', 'notes': 'A/E 1.01, H-L p=0.15'},
            {'section': 'Stability (PSI)', 'status': 'GREEN', 'notes': 'PSI 0.07 on score'},
            {'section': 'Fairness', 'status': 'GREEN', 'notes': 'No disparate impact identified'},
            {'section': 'Out-of-time', 'status': 'GREEN', 'notes': 'OOT Gini 0.40 vs in-sample 0.42'},
        ],
    },
    monitoring_results={
        'period': '2025-Q3',
        'ae_ratio': 1.02,
        'psi_score': 0.06,
        'gini': 0.41,
        'recommendation': 'Continue',
        'triggered_alerts': [],
    },
)

d = report.to_dict()
print("Report sections:")
for key in d:
    print(f"  {key}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Recommendations

# COMMAND ----------

recs = d['recommendations']
print(f"Recommendations ({len(recs)}):")
for i, rec in enumerate(recs, 1):
    print(f"  {i}. {rec}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Save the HTML governance pack

# COMMAND ----------

html_path = '/tmp/motor_freq_mrm_pack.html'
report.save_html(html_path)
print(f"HTML report saved to: {html_path}")
print(f"File size: {os.path.getsize(html_path):,} bytes")

# Verify it's valid HTML
with open(html_path) as f:
    content = f.read()
assert '<!DOCTYPE html>' in content
assert 'Motor TPPD Frequency' in content
print("HTML validation: OK")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Save the JSON report

# COMMAND ----------

json_path = '/tmp/motor_freq_mrm_pack.json'
report.save_json(json_path)
print(f"JSON report saved to: {json_path}")

import json
with open(json_path) as f:
    loaded = json.load(f)
print(f"Model ID in JSON: {loaded['model_identity']['model_id']}")
print(f"Tier in JSON: {loaded['risk_tier']['tier']}")
print(f"Overall RAG: {loaded['validation_summary']['overall_rag']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Standalone usage (no insurance-validation)
# MAGIC
# MAGIC The library works without insurance-validation or insurance-monitoring.
# MAGIC Pass validation and monitoring data as plain dicts.

# COMMAND ----------

# Minimal viable governance record for a new model
new_model_card = ModelCard(
    model_id='pet-freq-v1',
    model_name='Pet Insurance Frequency',
    version='1.0.0',
    model_class='pricing',
    intended_use='Claim frequency for dog and cat pet insurance',
    champion_challenger_status='challenger',
    gwp_impacted=8_000_000,
    customer_facing=True,
    developer='Pricing Team',
)

pet_tier = scorer.score(
    gwp_impacted=8_000_000,
    model_complexity='medium',
    deployment_status='challenger',
    regulatory_use=False,
    external_data=False,
    customer_facing=True,
)

print(f"Pet model tier: {pet_tier.tier} ({pet_tier.tier_label}), score: {pet_tier.score:.1f}")

# Generate a basic governance report with no validation data
basic_report = GovernanceReport(card=new_model_card, tier=pet_tier)
basic_html = basic_report.to_html()
assert 'Pet Insurance Frequency' in basic_html
print("Basic report generated OK")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC This demo showed the complete insurance-mrm governance workflow:
# MAGIC
# MAGIC | Step | What it produced |
# MAGIC |------|-----------------|
# MAGIC | ModelCard | Full governance record with 5 assumptions, 3 limitations, monitoring plan |
# MAGIC | RiskTierScorer | Composite score across 6 dimensions, verbose rationale |
# MAGIC | ModelInventory | 3-model registry with querying and audit log |
# MAGIC | GovernanceReport | Self-contained HTML governance pack, JSON sidecar |
# MAGIC
# MAGIC The library is dependency-free and works standalone.
# MAGIC Richer integration is available when insurance-validation and insurance-monitoring are installed.

# COMMAND ----------

print("Demo complete. All steps executed successfully.")

# COMMAND ----------

dbutils.notebook.exit("DEMO_COMPLETE")
