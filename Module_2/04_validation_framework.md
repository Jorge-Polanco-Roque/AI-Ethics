# Validation Framework

## Overview

Every fairness intervention must be validated across three dimensions: **fairness improvement**, **model performance**, and **business outcomes**. This framework provides the protocols, metrics, and thresholds that implementing teams use to verify their interventions are effective, safe, and sustainable.

> **Related documents**: This framework is referenced by [02_implementation_guide.md](02_implementation_guide.md) (Step 5: Validation & Deployment). For a practical demonstration of how validation was applied, see the [03_case_study.md](03_case_study.md). For intersectional validation details, see [05_intersectional_fairness.md](05_intersectional_fairness.md). For how validation adapts across domains, see [06_adaptability_guidelines.md](06_adaptability_guidelines.md).

---

## Validation Architecture

```mermaid
graph TD
    subgraph INPUT["Intervention Output"]
        A[Modified Model / Pipeline]
    end

    subgraph DIM1["Dimension 1: Fairness"]
        B1[Primary Fairness Metric]
        B2[Secondary Fairness Metrics]
        B3[Intersectional Analysis]
        B4[Statistical Significance]
    end

    subgraph DIM2["Dimension 2: Performance"]
        C1[Predictive Accuracy]
        C2[Calibration Quality]
        C3[Rank Ordering]
        C4[Feature Stability]
    end

    subgraph DIM3["Dimension 3: Business"]
        D1[Selection / Approval Rates]
        D2[Expected Loss / Revenue]
        D3[Customer Experience]
        D4[Regulatory Compliance]
    end

    subgraph VERDICT["Validation Verdict"]
        E{All three<br/>dimensions pass?}
        F[APPROVED:<br/>Deploy with monitoring]
        G[CONDITIONAL:<br/>Deploy with enhanced monitoring<br/>and review date]
        H[REJECTED:<br/>Iterate on intervention]
    end

    A --> B1 & B2 & B3 & B4
    A --> C1 & C2 & C3 & C4
    A --> D1 & D2 & D3 & D4

    B1 & B2 & B3 & B4 --> E
    C1 & C2 & C3 & C4 --> E
    D1 & D2 & D3 & D4 --> E

    E -->|All pass| F
    E -->|1-2 marginal| G
    E -->|Any fail| H

    style DIM1 fill:#e8f5e9,stroke:#4CAF50
    style DIM2 fill:#e3f2fd,stroke:#1565C0
    style DIM3 fill:#fff3e0,stroke:#FF9800
    style F fill:#c8e6c9,stroke:#4CAF50
    style G fill:#fff9c4,stroke:#FFC107
    style H fill:#ffcdd2,stroke:#E91E63
```

---

## Dimension 1: Fairness Validation

### Primary Fairness Metrics

Select the primary metric based on the fairness definition agreed with stakeholders:

| Fairness Definition | Metric | Formula | Target |
|-------------------|--------|---------|--------|
| Demographic Parity | Selection Rate Ratio | min(SR_a, SR_b) / max(SR_a, SR_b) | > 0.80 (4/5 rule) |
| Equal Opportunity | True Positive Rate Difference | \|TPR_a - TPR_b\| | < 0.05 |
| Equalized Odds | Max(TPR diff, FPR diff) | max(\|TPR_a - TPR_b\|, \|FPR_a - FPR_b\|) | < 0.05 |
| Predictive Parity | Positive Predictive Value Diff | \|PPV_a - PPV_b\| | < 0.05 |
| Calibration | Expected Calibration Error Gap | \|ECE_a - ECE_b\| | < 0.03 |

### Secondary Fairness Metrics

Even when optimizing for one definition, track others to ensure no metric degrades significantly:

```
FAIRNESS METRIC CHECKLIST
==========================
Primary metric (chosen definition):    [value] → [value]  Pass/Fail
Demographic parity ratio:              [value] → [value]  Monitor
Equal opportunity difference:          [value] → [value]  Monitor
Equalized odds (max gap):              [value] → [value]  Monitor
Calibration gap:                       [value] → [value]  Monitor

ALERT: Flag if any secondary metric degrades > 0.05 from baseline.
```

### Intersectional Fairness Validation

For each intersection of protected attributes (see [05_intersectional_fairness.md](05_intersectional_fairness.md)):

```mermaid
flowchart TD
    A[Define intersectional subgroups] --> B[Compute primary fairness<br/>metric per subgroup]
    B --> C{Any subgroup gap<br/>> 2x overall target?}
    C -->|No| D[Pass: Intersectional<br/>fairness maintained]
    C -->|Yes| E[Flag subgroup for<br/>targeted intervention]
    E --> F{Subgroup size<br/>> 100 samples?}
    F -->|Yes| G[Statistically reliable:<br/>require targeted fix]
    F -->|No| H[Insufficient data:<br/>document and monitor]

    style D fill:#c8e6c9,stroke:#4CAF50
    style G fill:#ffcdd2,stroke:#E91E63
    style H fill:#fff9c4,stroke:#FFC107
```

### Statistical Significance Testing

All fairness improvements must be statistically validated:

| Test | When to Use | Threshold |
|------|------------|-----------|
| Two-proportion z-test | Comparing rates (approval, selection) | p < 0.05 |
| Bootstrap confidence interval | Small samples or complex metrics | 95% CI excludes zero |
| Permutation test | Non-standard metrics, no distributional assumptions | p < 0.05 |
| Bonferroni correction | Multiple comparisons (intersectional groups) | p < 0.05 / n_comparisons |

**Template:**

```
STATISTICAL SIGNIFICANCE REPORT
================================
Test: [Two-proportion z-test / Bootstrap / Permutation]
Groups compared: [Group A vs. Group B]
Metric: [Metric name]
Before: [value] (95% CI: [lower, upper])
After:  [value] (95% CI: [lower, upper])
Difference: [value]
p-value: [value]
Conclusion: [Statistically significant / Not significant]

If intersectional (n comparisons = [n]):
Bonferroni-corrected threshold: [0.05/n]
```

---

## Dimension 2: Performance Validation

### Predictive Accuracy

| Metric | Formula | Acceptable Degradation |
|--------|---------|----------------------|
| AUC-ROC | Area under ROC curve | < 3% relative decrease |
| Accuracy | (TP + TN) / Total | < 3% absolute decrease |
| F1 Score | 2 × (Precision × Recall) / (Precision + Recall) | < 5% relative decrease |
| Precision | TP / (TP + FP) | Context-dependent |
| Recall | TP / (TP + FN) | Context-dependent |

### Calibration Quality

```mermaid
flowchart TD
    A[Generate reliability diagram<br/>per group] --> B[Compute ECE per group]
    B --> C{ECE < 0.05<br/>for all groups?}
    C -->|Yes| D[Calibration: PASS]
    C -->|No| E{ECE increased<br/>from baseline?}
    E -->|No - was already high| F[Calibration: MONITOR<br/>Pre-existing issue]
    E -->|Yes - intervention degraded it| G[Calibration: FAIL<br/>Intervention harmed calibration]

    style D fill:#c8e6c9,stroke:#4CAF50
    style F fill:#fff9c4,stroke:#FFC107
    style G fill:#ffcdd2,stroke:#E91E63
```

### Rank Ordering Preservation

Verify that the intervention preserves the relative ordering of predictions within groups:

| Check | Method | Threshold |
|-------|--------|-----------|
| Within-group rank stability | Spearman correlation (before vs. after) | ρ > 0.95 |
| Cross-group rank stability | Kendall's τ on full population | τ > 0.90 |
| Extreme predictions preserved | Top/bottom 5% overlap | > 80% overlap |

### Feature Importance Stability

| Check | Method | Threshold |
|-------|--------|-----------|
| Top-10 feature overlap | Jaccard similarity of top-10 lists | > 0.80 |
| Importance rank correlation | Spearman on feature importance vectors | ρ > 0.90 |
| SHAP value direction | Check no feature flipped sign | 0 flips allowed |

---

## Dimension 3: Business Validation

### Business Impact Assessment Template

```
BUSINESS IMPACT ASSESSMENT
===========================
System: [Name]
Date: [Date]
Assessor: [Name]

SELECTION / APPROVAL RATES:
- Overall rate before: [%]
- Overall rate after:  [%]
- Target range:        [%] - [%]
- Within target:       [Yes/No]

FINANCIAL IMPACT:
- Expected loss/revenue before: [$]
- Expected loss/revenue after:  [$]
- Net impact:                   [$]
- Acceptable threshold:         [$]
- Within threshold:             [Yes/No]

CUSTOMER EXPERIENCE:
- Affected population size: [N]
- Applicants gaining approval:  [N] ([%])
- Applicants losing approval:   [N] ([%])
- Net impact assessment:        [Positive/Neutral/Negative]

REGULATORY COMPLIANCE:
- Relevant regulations: [List]
- Compliance before:    [Status]
- Compliance after:     [Status]
- Legal review needed:  [Yes/No]

OPERATIONAL IMPACT:
- Inference latency change: [ms]
- Pipeline complexity added: [Description]
- Maintenance burden: [Low/Medium/High]
```

---

## Validation Protocol: Step-by-Step

### Pre-Validation Checklist

- [ ] Baseline metrics documented (fairness, performance, business)
- [ ] Test set is held-out (never used during intervention development)
- [ ] Test set is representative of production data
- [ ] Test set size sufficient for statistical power (> 1,000 per group minimum)
- [ ] Fairness definition and targets agreed with stakeholders
- [ ] Performance degradation threshold agreed

### Validation Execution

```mermaid
flowchart TD
    A[Collect baseline metrics<br/>on test set] --> B[Apply full intervention<br/>pipeline to test set]
    B --> C[Compute all metrics<br/>across 3 dimensions]

    C --> D[Fairness Validation]
    C --> E[Performance Validation]
    C --> F[Business Validation]

    D --> D1{Primary fairness<br/>metric improved?}
    D1 -->|Yes| D2{Statistically<br/>significant?}
    D1 -->|No| FAIL1[FAIL: No improvement]
    D2 -->|Yes| D3{Intersectional<br/>check passes?}
    D2 -->|No| FAIL2[FAIL: Not significant]
    D3 -->|Yes| PASS_D[Fairness: PASS]
    D3 -->|No| COND_D[Fairness: CONDITIONAL]

    E --> E1{AUC degradation<br/>< threshold?}
    E1 -->|Yes| E2{Calibration<br/>maintained?}
    E1 -->|No| FAIL3[FAIL: Performance loss]
    E2 -->|Yes| E3{Rank ordering<br/>preserved?}
    E2 -->|No| COND_E[Performance: CONDITIONAL]
    E3 -->|Yes| PASS_E[Performance: PASS]
    E3 -->|No| FAIL4[FAIL: Rank disruption]

    F --> F1{Business metrics<br/>within targets?}
    F1 -->|Yes| F2{Regulatory<br/>compliance OK?}
    F1 -->|No| FAIL5[FAIL: Business impact]
    F2 -->|Yes| PASS_F[Business: PASS]
    F2 -->|No| FAIL6[FAIL: Compliance issue]

    PASS_D & PASS_E & PASS_F --> APPROVED[APPROVED]
    COND_D & PASS_E & PASS_F --> CONDITIONAL[CONDITIONAL APPROVAL]
    PASS_D & COND_E & PASS_F --> CONDITIONAL

    FAIL1 & FAIL2 & FAIL3 & FAIL4 & FAIL5 & FAIL6 --> REJECTED[REJECTED: Iterate]

    style APPROVED fill:#c8e6c9,stroke:#4CAF50,stroke-width:2px
    style CONDITIONAL fill:#fff9c4,stroke:#FFC107,stroke-width:2px
    style REJECTED fill:#ffcdd2,stroke:#E91E63,stroke-width:2px
```

---

## Post-Deployment Monitoring

### Monitoring Dashboard

```mermaid
graph TD
    subgraph DAILY["Daily Checks"]
        A1[Approval rate by group]
        A2[Score distribution by group]
        A3[Volume by group]
    end

    subgraph WEEKLY["Weekly Checks"]
        B1[Full fairness metric suite]
        B2[Calibration ECE per group]
        B3[Feature drift detection]
    end

    subgraph MONTHLY["Monthly Checks"]
        C1[Complete validation rerun]
        C2[Intersectional analysis]
        C3[Business impact review]
    end

    subgraph ALERTS["Alert System"]
        D1[Level 1: Yellow Alert<br/>Metric degrades > 1%<br/>→ Investigate within 48h]
        D2[Level 2: Orange Alert<br/>Metric degrades > 3%<br/>→ Investigate within 24h]
        D3[Level 3: Red Alert<br/>Metric degrades > 5%<br/>→ Immediate review<br/>Consider rollback]
    end

    A1 & A2 & A3 --> D1
    B1 & B2 & B3 --> D2
    C1 & C2 & C3 --> D3

    style DAILY fill:#e3f2fd,stroke:#1565C0
    style WEEKLY fill:#e8f5e9,stroke:#4CAF50
    style MONTHLY fill:#fff3e0,stroke:#FF9800
    style D1 fill:#fff9c4,stroke:#FFC107
    style D2 fill:#ffe0b2,stroke:#FF9800
    style D3 fill:#ffcdd2,stroke:#E91E63
```

### Data Drift Detection

Monitor for shifts in the input data distribution that could affect fairness:

| What to Monitor | Method | Alert Threshold |
|----------------|--------|-----------------|
| Protected attribute distribution | Chi-squared test vs. training data | p < 0.05 |
| Feature distributions per group | Kolmogorov-Smirnov test | D > 0.1 |
| Label distribution per group | Proportion test | > 2% shift |
| Proxy variable correlations | Pearson/Spearman correlation change | > 0.1 change |
| Population composition | Group proportion change | > 5% shift |

### Incident Response Protocol

```mermaid
flowchart TD
    A[Fairness alert triggered] --> B{Alert level?}

    B -->|Yellow| C[Log incident.<br/>Investigate within 48h.<br/>Check if data drift.]
    B -->|Orange| D[Log incident.<br/>Notify tech lead.<br/>Investigate within 24h.]
    B -->|Red| E[Log incident.<br/>Notify VP.<br/>Consider immediate rollback<br/>to last known fair state.]

    C --> F{Root cause<br/>identified?}
    D --> F
    E --> F

    F -->|Data drift| G[Re-run Phase 4<br/>post-processing adjustment]
    F -->|Model degradation| H[Re-run Phases 3+4<br/>retrain with updated data]
    F -->|New bias source| I[Re-run full pipeline<br/>starting from Phase 1]
    F -->|False alarm| J[Update alert thresholds.<br/>Document in runbook.]

    G & H & I --> K[Re-validate using<br/>this framework]
    K --> L[Deploy fix +<br/>update monitoring]

    style E fill:#ffcdd2,stroke:#E91E63
    style D fill:#ffe0b2,stroke:#FF9800
    style C fill:#fff9c4,stroke:#FFC107
```

> **See also**: The re-entry triggers and corresponding pipeline entry points are detailed in the [Integration Workflow — When to Re-Enter the Pipeline](01_integration_workflow.md#when-to-re-enter-the-pipeline) table.

---

## Audit Trail Requirements

Every validation must produce a permanent audit record:

| Artifact | Content | Retention |
|----------|---------|-----------|
| Validation Report | Full metric suite across all 3 dimensions | 7 years (regulatory) |
| Test Data Snapshot | Anonymized test set used for validation | 7 years |
| Model Artifact | Exact model version validated | Lifetime of model |
| Configuration Record | All parameters, thresholds, techniques applied | 7 years |
| Decision Log | Who approved, when, with what conditions | 7 years |
| Monitoring Alerts | All triggered alerts and resolutions | 3 years |

### Validation Report Template

```
FAIRNESS INTERVENTION VALIDATION REPORT
========================================
Report ID: [UUID]
Date: [Date]
System: [Name]
Model Version: [Version]
Validator: [Name]
Approver: [Name]

1. INTERVENTION SUMMARY
   Phases applied: [1/2/3/4]
   Techniques used: [List]
   Fairness definition: [Definition]
   Target: [Metric < value]

2. FAIRNESS RESULTS
   Primary metric: [before] → [after] (p = [value])
   Secondary metrics: [table]
   Intersectional analysis: [summary]
   Statistical significance: [confirmed/not confirmed]

3. PERFORMANCE RESULTS
   AUC: [before] → [after] ([% change])
   Calibration: [ECE before] → [ECE after]
   Rank stability: [ρ = value]

4. BUSINESS RESULTS
   Approval rate: [before] → [after]
   Expected loss: [before] → [after]
   Regulatory status: [Compliant/Non-compliant]

5. VERDICT
   [ ] APPROVED - Deploy with standard monitoring
   [ ] CONDITIONAL - Deploy with enhanced monitoring until [date]
   [ ] REJECTED - Reason: [explanation]

6. MONITORING PLAN
   Daily checks: [list]
   Weekly checks: [list]
   Alert thresholds: [table]
   Review date: [date]

Signatures:
- Validator: _____________ Date: _______
- Tech Lead: _____________ Date: _______
- Compliance: ____________ Date: _______
```

---

## Success Criteria Summary

| Criterion | Must Pass | Should Pass | Nice to Have |
|-----------|:---------:|:-----------:|:------------:|
| Primary fairness metric improved | X | | |
| Improvement statistically significant | X | | |
| No intersectional group > 2x target | | X | |
| AUC degradation < threshold | X | | |
| Calibration maintained or improved | | X | |
| Rank ordering preserved (ρ > 0.95) | | X | |
| Business metrics within targets | X | | |
| Regulatory compliance maintained | X | | |
| Feature importance stable | | | X |
| Consistent across random seeds | | X | |
| Monitoring configured and tested | X | | |
