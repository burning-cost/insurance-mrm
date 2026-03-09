# Databricks notebook source
# COMMAND ----------

# MAGIC %md
# MAGIC # insurance-mrm: Demo Runner
# MAGIC
# MAGIC Runs the demo workflow as a Python script (not as a notebook magic cell).

# COMMAND ----------

import subprocess, sys, shutil, os

# Copy from workspace to /tmp
src = "/Workspace/insurance-mrm"
dst = "/tmp/insurance-mrm"
if os.path.exists(dst):
    shutil.rmtree(dst)
shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
print("Copied project to", dst)

# Install
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-e", dst, "--quiet"],
    capture_output=True, text=True,
)
if result.returncode != 0:
    print("INSTALL FAILED:", result.stderr[:2000])
else:
    print("Install OK")

# COMMAND ----------

# Run the demo as a script
demo_script = """
import sys
sys.path.insert(0, '/tmp/insurance-mrm/src')

from insurance_mrm import (
    ModelCard, Assumption, Limitation,
    ModelInventory, RiskTierScorer, GovernanceReport,
)
import tempfile, os, json

print("=== 1. ModelCard ===")
card = ModelCard(
    model_id='motor-freq-tppd-v2',
    model_name='Motor TPPD Frequency',
    version='2.1.0',
    model_class='pricing',
    intended_use='Frequency pricing for private motor.',
    not_intended_for=['Commercial motor', 'Fleet'],
    target_variable='claim_count',
    distribution_family='Poisson',
    model_type='CatBoost',
    rating_factors=['driver_age', 'vehicle_age', 'region'],
    training_data_period=('2019-01-01', '2023-12-31'),
    developer='Pricing Team',
    champion_challenger_status='champion',
    gwp_impacted=125_000_000,
    customer_facing=True,
    assumptions=[
        Assumption('Frequency stationarity since 2022', risk='MEDIUM', mitigation='Quarterly A/E'),
        Assumption('Region as road density proxy', risk='LOW'),
        Assumption('No EV structural break', risk='HIGH', mitigation='EV segment review at 15%'),
    ],
    limitations=[
        Limitation('Thin data for vehicles >10 years', impact='High variance', population_at_risk='8% of book'),
    ],
    outstanding_issues=['VIF check pending'],
    approved_by=['Chief Actuary', 'MRC'],
    approval_date='2024-10-15',
    next_review_date='2025-10-15',
    monitoring_owner='Sarah Ahmed',
    monitoring_triggers={'psi_score': 0.25, 'ae_ratio_deviation': 0.10},
    overall_rag='GREEN',
    materiality_tier=1,
)
print(f"  model_id: {card.model_id}")
print(f"  assumptions: {len(card.assumptions)}, HIGH: {len(card.high_risk_assumptions)}")
print(f"  is_approved: {card.is_approved}")

print()
print("=== 2. RiskTierScorer ===")
scorer = RiskTierScorer()
tier = scorer.score(
    gwp_impacted=125_000_000,
    model_complexity='high',
    deployment_status='champion',
    regulatory_use=False,
    external_data=False,
    customer_facing=True,
    validation_months_ago=12.0,
    drift_triggers_last_year=0,
)
print(f"  Tier: {tier.tier} ({tier.tier_label})")
print(f"  Score: {tier.score:.1f}/100")
print(f"  Review: {tier.review_frequency}, Sign-off: {tier.sign_off_requirement}")
for dim in tier.dimensions:
    w = tier.weights_used[dim.name]
    contrib = (dim.score / dim.max_score) * w
    print(f"    {dim.name:<25} {contrib:>5.1f}pts  {dim.rationale}")

print()
print("=== 3. ModelInventory ===")
registry = os.path.join(tempfile.mkdtemp(), 'mrm.json')
inv = ModelInventory(registry)
inv.register(card, tier)

card2 = ModelCard(
    model_id='home-bld-v1',
    model_name='Home Buildings Severity',
    version='1.0.0',
    model_class='pricing',
    champion_challenger_status='champion',
    gwp_impacted=45_000_000,
    customer_facing=True,
    next_review_date='2026-06-01',
    monitoring_owner='James Brown',
    overall_rag='AMBER',
)
tier2 = scorer.score(45_000_000, 'medium', 'champion', False, False, True)
inv.register(card2, tier2)

print(f"  Registered {len(inv.list())} models")
summary = inv.summary()
print(f"  Summary: {summary['total_models']} models, by_tier={summary['by_tier']}")

champions = inv.list(status='champion')
print(f"  Champion models: {[m['model_name'] for m in champions]}")

inv.log_event('motor-freq-tppd-v2', 'validation_complete', 'Annual validation passed GREEN')
events = inv.events(model_id='motor-freq-tppd-v2')
print(f"  Events logged: {len(events)}")

print()
print("=== 4. GovernanceReport ===")
report = GovernanceReport(
    card=card,
    tier=tier,
    validation_results={
        'overall_rag': 'GREEN',
        'run_id': 'run-abc-123',
        'run_date': '2024-10-01',
        'gini': 0.42,
        'ae_ratio': 1.01,
        'psi_score': 0.07,
        'section_results': [
            {'section': 'Data Quality', 'status': 'GREEN', 'notes': 'All OK'},
            {'section': 'Discrimination', 'status': 'GREEN', 'notes': 'Gini 0.42'},
            {'section': 'Calibration', 'status': 'AMBER', 'notes': 'H-L borderline'},
        ],
    },
    monitoring_results={
        'period': '2025-Q3', 'ae_ratio': 1.02, 'psi_score': 0.06,
        'gini': 0.41, 'recommendation': 'Continue',
    },
)

d = report.to_dict()
assert d['model_identity']['model_id'] == 'motor-freq-tppd-v2'
assert d['risk_tier']['tier'] == tier.tier
assert d['validation_summary']['overall_rag'] == 'GREEN'

html = report.to_html()
assert '<!DOCTYPE html>' in html
assert 'Motor TPPD Frequency' in html
assert 'GREEN' in html
html_size = len(html)
print(f"  HTML report: {html_size:,} chars, sections: {len(d)}")

report_json = json.loads(report.to_json())
print(f"  JSON report: tier={report_json['risk_tier']['tier']}, "
      f"rag={report_json['validation_summary']['overall_rag']}")

recs = d['recommendations']
print(f"  Recommendations: {len(recs)}")
for r in recs:
    print(f"    - {r[:80]}")

print()
print("=== 5. Serialisation roundtrip ===")
card_json = card.to_json()
card_back = ModelCard.from_json(card_json)
assert card_back.model_id == card.model_id
assert len(card_back.assumptions) == len(card.assumptions)
assert card_back.assumptions[0].risk == 'MEDIUM'
print(f"  ModelCard JSON roundtrip: OK ({len(card_json)} chars)")

tier_dict = tier.to_dict()
assert tier_dict['tier'] == tier.tier
assert len(tier_dict['dimensions']) == 6
print(f"  TierResult serialisation: OK")

print()
print("ALL CHECKS PASSED")
"""

result = subprocess.run(
    [sys.executable, "-c", demo_script],
    capture_output=True, text=True,
    env={**os.environ, "PYTHONPATH": "/tmp/insurance-mrm/src"},
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:2000])
print("Exit code:", result.returncode)
assert result.returncode == 0, "Demo failed"

# COMMAND ----------

dbutils.notebook.exit("DEMO_COMPLETE")
