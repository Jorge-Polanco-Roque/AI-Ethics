# Intersectional Fairness Guide

## Why Intersectionality Matters

Single-axis fairness analysis (gender alone, race alone) can miss compounding effects. A system may appear fair for women overall and fair for older applicants overall, while being systematically unfair to *older women specifically*. Crenshaw (1989) introduced the concept of intersectionality to describe how multiple dimensions of identity interact to create unique experiences of discrimination.

**Example from our loan system** (see [03_case_study.md](03_case_study.md)): After initial interventions, the overall gender gap was 4%. But women aged 25-35 still faced a 12% gap — three times the overall figure. This subgroup gap would be invisible in single-axis analysis.

> **Related documents**: This guide applies across all four phases described in [01_integration_workflow.md](01_integration_workflow.md). For validation of intersectional fairness, see [04_validation_framework.md](04_validation_framework.md). For domain-specific intersectional considerations, see [06_adaptability_guidelines.md](06_adaptability_guidelines.md).

---

## Intersectional Analysis Framework

```mermaid
flowchart TD
    A[Define protected<br/>attributes in scope] --> B[Generate intersectional<br/>subgroups]
    B --> C[Prioritize subgroups<br/>for analysis]
    C --> D[Compute fairness metrics<br/>per subgroup]
    D --> E{Any subgroup<br/>significantly worse<br/>than overall?}
    E -->|No| F[Intersectional<br/>fairness maintained]
    E -->|Yes| G[Targeted intervention<br/>design]
    G --> H[Validate targeted<br/>intervention]
    H --> I{Improvement<br/>without harming<br/>other subgroups?}
    I -->|Yes| J[Deploy targeted fix]
    I -->|No| K[Revise approach:<br/>broader intervention needed]
    K --> G

    style F fill:#c8e6c9,stroke:#4CAF50
    style J fill:#c8e6c9,stroke:#4CAF50
```

---

## Step 1: Subgroup Generation and Prioritization

### The Combinatorial Challenge

With *k* protected attributes each having *n_i* categories, the number of intersectional subgroups is:

**Total subgroups = n_1 x n_2 x ... x n_k**

For example: 2 genders x 4 age groups x 3 race categories = 24 subgroups. Not all will have sufficient data for meaningful analysis.

### Prioritization Framework

```mermaid
flowchart TD
    A[All possible<br/>intersectional subgroups] --> B[Filter by sample size<br/>n > 100 per subgroup]
    B --> C[Rank by historical<br/>vulnerability]
    C --> D[Top-priority subgroups<br/>Tier 1: Analyze in every phase]
    C --> E[Medium-priority subgroups<br/>Tier 2: Analyze in validation]
    C --> F[Low-priority subgroups<br/>Tier 3: Monitor post-deployment]

    D --> G["Example Tier 1:<br/>Women aged 25-35<br/>Minority women<br/>Older minority men"]
    E --> H["Example Tier 2:<br/>All other 2-way intersections<br/>with n > 200"]
    F --> I["Example Tier 3:<br/>3-way intersections<br/>Small subgroups (n < 200)"]

    style D fill:#ffcdd2,stroke:#E91E63
    style E fill:#fff9c4,stroke:#FFC107
    style F fill:#e3f2fd,stroke:#1565C0
```

### Prioritization Scoring

| Factor | Weight | Scoring |
|--------|:------:|---------|
| Historical disadvantage | 30% | Known marginalized group = 3; Potentially disadvantaged = 2; No known issues = 1 |
| Subgroup size | 25% | > 1000 = 3; 200-1000 = 2; 100-200 = 1 |
| Observed disparity magnitude | 25% | Gap > 2x overall = 3; Gap > 1.5x = 2; Gap ≈ overall = 1 |
| Legal/regulatory sensitivity | 20% | Explicitly protected intersection = 3; Implicitly protected = 2; Not specified = 1 |

**Priority score = weighted sum. Tier 1: score > 2.5. Tier 2: score 1.5-2.5. Tier 3: score < 1.5.**

---

## Step 2: Intersectionality in Each Phase

### Phase 1: Causal Analysis — Intersectional Considerations

```mermaid
flowchart TD
    A[Standard DAG<br/>Single protected attribute] --> B[Extend DAG with<br/>intersectional nodes]
    B --> C[Add interaction edges:<br/>Gender × Age → Employment Pattern]
    C --> D[Identify intersection-specific<br/>causal pathways]
    D --> E[Example: Career break penalty<br/>affects women aged 25-35<br/>much more than women 45+]

    style E fill:#fff3e0,stroke:#FF9800
```

**Key actions:**
- Extend the causal DAG to include interaction effects between protected attributes
- Identify pathways that are specific to intersectional subgroups (e.g., career breaks disproportionately affect women of child-bearing age)
- Run counterfactual analysis for Tier 1 subgroups specifically
- Document which pathways contribute most to each subgroup's disparity

**Template addition for Pathway Classification Report:**

```
INTERSECTIONAL PATHWAY ANALYSIS
================================
Pathway: [ID]
Subgroup-specific effects:
- [Subgroup 1]: [Effect size] — [Notes]
- [Subgroup 2]: [Effect size] — [Notes]
- [Subgroup 3]: [Effect size] — [Notes]

Interaction effect detected: [Yes/No]
If yes: [Description of how protected attributes interact on this pathway]
```

### Phase 2: Pre-Processing — Intersectional Considerations

```mermaid
flowchart TD
    A[Standard pre-processing<br/>technique selected] --> B{Does the technique<br/>handle intersectionality?}
    B -->|Yes, natively| C[Apply with intersectional<br/>group definitions]
    B -->|No| D[Extend technique<br/>for intersections]

    D --> D1[Reweighting: compute weights<br/>per intersectional subgroup<br/>not just per single attribute]
    D --> D2[DI Removal: apply repair<br/>per intersectional subgroup<br/>not just per single attribute]
    D --> D3[Fair Representations: include<br/>multiple adversary heads,<br/>one per protected attribute]

    C & D1 & D2 & D3 --> E[Evaluate fairness per<br/>intersectional subgroup]
    E --> F{Any subgroup<br/>gap worsened?}
    F -->|No| G[Pass: Proceed]
    F -->|Yes| H[Adjust: subgroup-specific<br/>parameter tuning]
    H --> E

    style G fill:#c8e6c9,stroke:#4CAF50
```

**Key actions:**
- Compute reweighting factors per intersectional subgroup, not just per single attribute
- When using Disparate Impact Removal, apply repair within intersectional groups
- After any transformation, verify that **no** intersectional subgroup's fairness *worsened*
- Use the "do no harm" principle: improvements for one subgroup must not come at the expense of another

**Example — Intersectional Reweighting:**

| Subgroup | Population % | Positive Outcome % | Standard Weight | Intersectional Weight |
|----------|:-----------:|:------------------:|:--------------:|:--------------------:|
| Male, age 25-35 | 22% | 78% | 0.95 | 0.90 |
| Male, age 36-50 | 18% | 80% | 0.92 | 0.88 |
| Female, age 25-35 | 20% | 52% | 1.15 | 1.45 |
| Female, age 36-50 | 15% | 62% | 1.08 | 1.20 |
| Male, age 50+ | 14% | 74% | 0.98 | 0.95 |
| Female, age 50+ | 11% | 58% | 1.12 | 1.30 |

Notice how intersectional weights amplify the correction for the most disadvantaged subgroup (women aged 25-35).

### Phase 3: In-Processing — Intersectional Considerations

```mermaid
flowchart TD
    A[Select in-processing<br/>technique] --> B{Multiple protected<br/>attributes?}
    B -->|Single| C[Standard single-axis<br/>constraint]
    B -->|Multiple| D[Multi-constraint<br/>approach]

    D --> D1["Option A: Joint Constraint<br/>Optimize for worst-case<br/>subgroup (minimax fairness)"]
    D --> D2["Option B: Per-Group Constraints<br/>Separate constraint per<br/>intersectional subgroup"]
    D --> D3["Option C: Hierarchical<br/>Primary constraint on main axis<br/>Secondary on intersections"]

    D1 --> E[Pro: Guarantees no subgroup<br/>is severely disadvantaged<br/>Con: May over-constrain model]
    D2 --> F[Pro: Precise per-group control<br/>Con: Many constraints →<br/>optimization difficulty]
    D3 --> G[Pro: Balanced approach<br/>Con: Must choose hierarchy]

    style D1 fill:#e8f5e9,stroke:#4CAF50
    style D2 fill:#e3f2fd,stroke:#1565C0
    style D3 fill:#fff3e0,stroke:#FF9800
```

**Recommended approach: Minimax Fairness**

Instead of optimizing for average fairness across groups, optimize for the worst-off subgroup:

```
Minimize: Loss(model)
Subject to: max_g |FairnessMetric(group_g) - target| < epsilon
            for all intersectional subgroups g with n_g > 100
```

This prevents "fairness gerrymandering" where aggregate metrics look good but specific subgroups remain disadvantaged (Kearns et al., 2018).

### Phase 4: Post-Processing — Intersectional Considerations

```mermaid
flowchart TD
    A[Post-processing<br/>technique selected] --> B{Threshold strategy?}

    B -->|Group-specific thresholds| C[Set thresholds per<br/>intersectional subgroup]
    B -->|Score transformation| D[Transform scores per<br/>intersectional subgroup]
    B -->|Calibration| E[Calibrate per<br/>intersectional subgroup]

    C & D & E --> F{Sufficient data per<br/>subgroup for reliable<br/>threshold/calibration?}

    F -->|Yes: n > 500| G[Apply subgroup-specific<br/>adjustment]
    F -->|Marginal: 100-500| H[Apply single-axis adjustment<br/>+ monitor intersections]
    F -->|No: n < 100| I[Apply overall adjustment<br/>+ flag for future review]

    G & H & I --> J[Verify: no subgroup<br/>fairness degraded]

    style G fill:#c8e6c9,stroke:#4CAF50
    style H fill:#fff9c4,stroke:#FFC107
    style I fill:#ffe0b2,stroke:#FF9800
```

**Key challenge**: Post-processing adjustments per intersectional subgroup require sufficient data. With 24 subgroups, some may be too small for reliable threshold estimation. Use hierarchical smoothing:

1. Estimate subgroup-specific parameters
2. Shrink toward the single-axis group parameter based on subgroup sample size
3. The smaller the subgroup, the more it relies on the broader group estimate

---

## Step 3: Intersectional Monitoring

### Monitoring Dashboard Extensions

Add these intersectional views to the standard monitoring dashboard:

| View | Frequency | Purpose |
|------|-----------|---------|
| Subgroup fairness heatmap | Weekly | Visual scan for emerging disparities |
| Worst-case subgroup metric | Daily | Early warning for most vulnerable group |
| Subgroup metric trends | Monthly | Detect gradual degradation |
| New subgroup detection | Monthly | Population shift may create new intersections |

### Intersectional Heatmap Example

```mermaid
block-beta
    columns 4
    space:1 A["Age 25-35"] B["Age 36-50"] C["Age 50+"]
    D["Male"]:1 E["0.5% gap ✅"]:1 F["0.3% gap ✅"]:1 G["0.8% gap ✅"]:1
    H["Female"]:1 I["1.5% gap ⚠️"]:1 J["0.6% gap ✅"]:1 K["1.1% gap ⚠️"]:1

    style E fill:#c8e6c9
    style F fill:#c8e6c9
    style G fill:#c8e6c9
    style J fill:#c8e6c9
    style I fill:#fff9c4
    style K fill:#fff9c4
```

---

## Handling the Impossibility Results

### Chouldechova-Kleinberg Impossibility

When base rates differ across groups (which they almost always do in practice), it is mathematically impossible to simultaneously satisfy:
1. Calibration (equal PPV across groups)
2. Equal false positive rates
3. Equal false negative rates

**Intersectional implication**: Base rate differences are often *larger* at intersectional levels, making the impossibility more acute.

```mermaid
flowchart TD
    A[Base rates differ<br/>across intersectional groups] --> B[Cannot satisfy all<br/>fairness criteria simultaneously]
    B --> C{Which criterion<br/>to prioritize?}

    C -->|Stakes are about<br/>opportunity access| D[Prioritize Equal Opportunity<br/>Equal TPR across groups]
    C -->|Stakes are about<br/>accurate probability| E[Prioritize Calibration<br/>Equal PPV across groups]
    C -->|Stakes are about<br/>equal treatment| F[Prioritize Demographic Parity<br/>Equal selection rates]

    D & E & F --> G[Document the trade-off<br/>explicitly for each<br/>intersectional subgroup]
    G --> H[Monitor the deprioritized<br/>metrics to ensure they<br/>don't degrade severely]

    style G fill:#fff3e0,stroke:#FF9800
```

### Practical Resolution

1. **Choose the primary fairness criterion** based on the system's purpose and stakeholder agreement
2. **Set floors for secondary criteria**: "We optimize for equal opportunity, but no group's calibration can deviate by more than 10%"
3. **Document the trade-off per subgroup**: Show stakeholders exactly what is being traded and why
4. **Review periodically**: As base rates evolve, the trade-off may shift

---

## Intersectional Fairness Checklist

Use this checklist at each phase of the playbook:

### Phase 1 (Causal Analysis)
- [ ] Protected attributes and their intersections identified
- [ ] Subgroups prioritized using scoring framework
- [ ] Causal DAG extended with interaction effects
- [ ] Counterfactual analysis run for Tier 1 subgroups
- [ ] Intersection-specific pathways documented

### Phase 2 (Pre-Processing)
- [ ] Reweighting/transformation applied per intersectional subgroup (not just single axis)
- [ ] "Do no harm" check: no subgroup fairness worsened
- [ ] Intersectional evaluation metrics computed

### Phase 3 (In-Processing)
- [ ] Fairness constraints include intersectional groups
- [ ] Minimax fairness considered (optimize for worst-off subgroup)
- [ ] Pareto frontier includes intersectional metrics

### Phase 4 (Post-Processing)
- [ ] Sufficient data per subgroup for reliable adjustment
- [ ] Hierarchical smoothing applied for small subgroups
- [ ] Post-processing verified across all Tier 1 subgroups

### Validation
- [ ] All Tier 1 subgroups pass fairness targets (or within 2x tolerance)
- [ ] Statistical tests use Bonferroni correction for multiple comparisons
- [ ] Heatmap visualization prepared for stakeholder review
- [ ] Monitoring configured for worst-case subgroup metric
