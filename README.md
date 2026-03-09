# insurance-mrm

Model risk management framework for insurance pricing models.

## The problem

Most UK insurers govern their pricing models with Word documents and Excel registers. A validation report is produced once at model launch, filed away, and referenced occasionally. Monitoring evidence (if it exists) lives in a separate tracker maintained by the pricing team. There is no audit trail connecting monitoring outputs to governance sign-offs.

This is not a criticism of any specific firm — it is a description of current practice across the market. The PRA's 2026 supervision priorities letter called out "gaps between assumed and realised profitability" for general insurers. PRA SS1/23 is expected to extend to insurers by 2026-2027. The current documentation approach will not survive a PRA model risk review.

`insurance-mrm` is the governance layer that sits on top of statistical validation and monitoring. It does not run statistical tests. Those are handled by `insurance-validation` (point-in-time validation reports) and `insurance-monitoring` (ongoing operational monitoring). What `insurance-mrm` provides is:

- A **model card** format with the fields a Model Risk Committee actually needs: assumptions register with risk ratings per assumption, explicit not-intended-for list, monitoring plan with named owner and trigger thresholds
- An **objective risk tier scoring engine** (0-100 composite score across 6 dimensions) that produces a defensible tier assignment with a verbose rationale string — not a judgment call
- A **persistent model inventory** backed by a plain JSON file, queryable by tier, status, owner, and review due date
- An **executive committee report** (HTML and JSON) that pulls together model identity, tier, validation status, monitoring summary, material assumptions, outstanding issues, and sign-off chain into a 2-3 page governance pack

## Installation

```bash
pip install insurance-mrm
```

No mandatory dependencies beyond the standard library. Optional: `insurance-validation` and `insurance-monitoring` for richer integration.

## Quickstart

```python
from insurance_mrm import (
    ModelCard, Assumption, Limitation,
    ModelInventory, RiskTierScorer, GovernanceReport,
)

# 1. Build a model card
card = ModelCard(
    model_id='motor-freq-tppd-v2',
    model_name='Motor TPPD Frequency',
    version='2.1.0',
    model_class='pricing',
    intended_use='Frequency pricing for private motor. Not for commercial motor, fleet, or reserving.',
    not_intended_for=['Commercial motor', 'Fleet', 'Reserving', 'Capital'],
    target_variable='claim_count',
    distribution_family='Poisson',
    model_type='CatBoost',
    rating_factors=['driver_age', 'vehicle_age', 'annual_mileage', 'region'],
    training_data_period=('2019-01-01', '2023-12-31'),
    developer='Pricing Team',
    champion_challenger_status='champion',
    gwp_impacted=125_000_000,
    customer_facing=True,
    regulatory_use=False,
    assumptions=[
        Assumption(
            description='Claim frequency stationarity since 2022',
            risk='MEDIUM',
            mitigation='Quarterly A/E monitoring, PSI alert at >0.25',
        ),
        Assumption(
            description='Region as proxy for road density and theft risk',
            risk='LOW',
        ),
    ],
    limitations=[
        Limitation(
            description='Performance degrades for vehicles >10 years (thin training data)',
            impact='Higher prediction variance for this segment',
            population_at_risk='~8% of book',
        ),
    ],
    outstanding_issues=['VIF check on driver_age x annual_mileage pending'],
    approved_by=['Chief Actuary', 'Model Risk Committee'],
    approval_date='2024-10-15',
    approval_conditions='Subject to quarterly A/E monitoring',
    next_review_date='2025-10-15',
    monitoring_owner='Sarah Ahmed, Head of Pricing Analytics',
    monitoring_frequency='Quarterly',
    monitoring_triggers={'psi_score': 0.25, 'ae_ratio_deviation': 0.10, 'gini_drop_pct': 0.05},
)

# 2. Score the risk tier
scorer = RiskTierScorer()
tier = scorer.score(
    gwp_impacted=125_000_000,
    model_complexity='high',          # 'low' | 'medium' | 'high'
    deployment_status='champion',     # 'champion' | 'challenger' | 'shadow' | 'development' | 'retired'
    regulatory_use=False,
    external_data=False,
    customer_facing=True,
    validation_months_ago=6.0,
    drift_triggers_last_year=0,
)
print(f"Tier {tier.tier} ({tier.tier_label}): {tier.score:.1f}/100")
print(tier.rationale)

# 3. Register in the inventory
inventory = ModelInventory('mrm_registry.json')
inventory.register(card, tier)

due = inventory.due_for_review(within_days=60)
for model in due:
    print(f"{model['model_name']} — review due {model['next_review_date']}")

# 4. Generate the governance pack
report = GovernanceReport(
    card=card,
    tier=tier,
    validation_results={
        'overall_rag': 'GREEN',
        'run_id': 'a1b2c3d4-uuid',
        'run_date': '2024-10-01',
        'gini': 0.42,
        'ae_ratio': 1.01,
        'psi_score': 0.07,
    },
    monitoring_results={
        'period': '2025-Q3',
        'ae_ratio': 1.02,
        'psi_score': 0.06,
        'recommendation': 'Continue',
    },
)
report.save_html('motor_freq_mrm_pack.html')
```

## Risk tier scoring

The scorer produces a 0-100 composite score across 6 dimensions. Weights sum to 100 and are configurable.

| Dimension | What it measures | Max pts (default) |
|-----------|-----------------|-------------------|
| Materiality | GWP influenced by the model | 25 |
| Complexity | Model architecture and feature count | 20 |
| Data quality | Use of external data sources | 10 |
| Validation coverage | Months since last independent validation | 10 |
| Drift history | Monitoring trigger events in last 12 months | 10 |
| Regulatory exposure | Production status + regulatory use + customer-facing pricing | 25 |

**Tier thresholds (defaults):**

| Score | Tier | Label | Review | Sign-off |
|-------|------|-------|--------|---------|
| >= 60 | 1 | Critical | Annual | Model Risk Committee |
| 30-59 | 2 | High | 18 months | Chief Actuary |
| < 30 | 3 | Medium | 24 months | Head of Pricing |

Override weights and thresholds at construction:

```python
scorer = RiskTierScorer(
    weights={
        'materiality': 35, 'complexity': 20, 'data_quality': 5,
        'validation_coverage': 15, 'drift_history': 10, 'regulatory_exposure': 15,
    },
    thresholds={1: 65, 2: 35, 3: 0},
)
```

## Model inventory

```python
inventory = ModelInventory('mrm_registry.json')

# Register
inventory.register(card, tier)

# Query
rows = inventory.list()
rows = inventory.list(status='champion')
rows = inventory.list(tier=1)
rows = inventory.list(owner='Sarah')
due = inventory.due_for_review(within_days=60)
overdue = inventory.overdue()

# Update after validation
inventory.update_validation(
    model_id='motor-freq-tppd-v2',
    validation_date='2025-10-01',
    overall_rag='GREEN',
    next_review_date='2026-10-01',
    run_id='uuid-from-insurance-validation',
)

# Audit log
inventory.log_event(
    model_id='motor-freq-tppd-v2',
    event_type='monitoring_trigger',
    description='PSI exceeded 0.25 on driver_age feature',
)

print(inventory.summary())
```

The inventory file is plain JSON and git-auditable. Treat it as source-controlled documentation.

## Regulatory context

Designed with PRA SS1/23 Principles 1 and 5 in mind. SS1/23 is currently scoped to banks but is expected to extend to insurers by 2026-2027. The tier scoring rubric and model card fields align with SS1/23 expectations.

FCA Consumer Duty (PRIN 2A.9) requires firms to regularly evidence customer outcomes. The monitoring plan fields and trigger thresholds on the model card support this documentation requirement.

## Part of the Burning Cost ecosystem

`insurance-mrm` is library 28 in the Burning Cost portfolio. It is the governance wrapper for:

- `insurance-validation` — point-in-time technical validation reports
- `insurance-monitoring` — ongoing operational monitoring

A team using all three has a complete, auditable, PRA-aligned pricing model governance workflow in Python.

## Licence

MIT
