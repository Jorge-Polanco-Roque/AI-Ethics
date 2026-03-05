# Integration Workflow: Connecting the Four Components

## Overview

The Fairness Intervention Playbook operates as a sequential pipeline where each phase's outputs inform the next phase's inputs. This document details the information flows, decision logic, and feedback mechanisms that connect the four components into a coherent intervention strategy.

> **Related documents**: For step-by-step implementation instructions, see [02_implementation_guide.md](02_implementation_guide.md). For a practical end-to-end demonstration, see [03_case_study.md](03_case_study.md). For validation protocols at each checkpoint, see [04_validation_framework.md](04_validation_framework.md). For intersectional considerations at each phase, see [05_intersectional_fairness.md](05_intersectional_fairness.md).

---

## End-to-End Pipeline

```mermaid
sequenceDiagram
    participant FA as Phase 1:<br/>Causal Analysis
    participant PP as Phase 2:<br/>Pre-Processing
    participant IP as Phase 3:<br/>In-Processing
    participant PO as Phase 4:<br/>Post-Processing
    participant VF as Validation<br/>Framework

    Note over FA: INPUT: Fairness metrics showing disparity

    FA->>FA: Build Structural Causal Model (DAG)
    FA->>FA: Identify discrimination pathways
    FA->>FA: Run counterfactual analysis
    FA->>FA: Map intervention points

    FA->>PP: Pathway Classification Report<br/>(which pathways need data fixes)
    FA->>IP: Pathway Classification Report<br/>(which pathways need model fixes)
    FA->>PO: Pathway Classification Report<br/>(which pathways need output fixes)

    Note over PP: INPUT: Causal pathway map + training data

    PP->>PP: Select techniques per pathway
    PP->>PP: Configure & apply transformations
    PP->>PP: Validate data quality

    PP->>VF: Pre-processing evaluation report
    VF->>VF: Check: bias reduced enough?

    alt Bias within tolerance
        VF-->>PO: Skip to monitoring
    else Residual bias remains
        PP->>IP: Transformed dataset +<br/>remaining bias report
    end

    Note over IP: INPUT: Transformed data + residual bias analysis

    IP->>IP: Analyze model architecture
    IP->>IP: Select fairness technique
    IP->>IP: Train with constraints
    IP->>IP: Validate on held-out set

    IP->>VF: In-processing evaluation report
    VF->>VF: Check: bias reduced enough?

    alt Bias within tolerance
        VF-->>PO: Skip to monitoring
    else Residual bias remains
        IP->>PO: Trained model +<br/>remaining bias report
    end

    Note over PO: INPUT: Trained model + prediction disparities

    PO->>PO: Optimize thresholds
    PO->>PO: Calibrate probabilities
    PO->>PO: Transform scores

    PO->>VF: Post-processing evaluation report
    VF->>VF: Final validation

    Note over VF: Continuous monitoring begins
```

---

## Phase 1: Causal Fairness Analysis — Detailed Workflow

### Purpose
Understand the causal mechanisms behind observed disparities. Without causal understanding, interventions risk being superficial (treating symptoms, not causes) or harmful (removing legitimate signals).

### Inputs
- Observed fairness metrics showing disparity (e.g., approval rate gap)
- Domain knowledge about the system and its variables
- Historical data for causal inference

### Process

```mermaid
flowchart TD
    A[Observed Disparity] --> B[Variable Identification]
    B --> B1[Protected Attributes<br/>e.g., gender, race, age]
    B --> B2[Mediators<br/>e.g., employment history, income]
    B --> B3[Proxy Variables<br/>e.g., part-time status, zip code]
    B --> B4[Outcome Variables<br/>e.g., loan approval, default risk]
    B --> B5[Legitimate Predictors<br/>e.g., credit score, debt ratio]

    B1 & B2 & B3 & B4 & B5 --> C[Causal Graph Construction]

    C --> D[Path Classification]
    D --> D1[Direct Paths<br/>Protected → Outcome]
    D --> D2[Mediated Paths<br/>Protected → Mediator → Outcome]
    D --> D3[Proxy Paths<br/>Protected ↔ Proxy → Outcome]
    D --> D4[Confounded Paths<br/>Confounder → Protected & Outcome]

    D1 & D2 & D3 & D4 --> E[Counterfactual Analysis]
    E --> E1[Estimate path-specific effects]
    E --> E2[Quantify each pathway's<br/>contribution to disparity]
    E --> E3[Classify pathways as<br/>legitimate vs. problematic]

    E1 & E2 & E3 --> F[Intervention Point Map]
    F --> F1[Data-level fixes needed]
    F --> F2[Model-level fixes needed]
    F --> F3[Output-level fixes needed]

    style A fill:#fff3e0,stroke:#FF9800
    style F fill:#e8f5e9,stroke:#4CAF50
```

### Outputs → Pathway Classification Report

The Pathway Classification Report is the key artifact that feeds into all subsequent phases. It contains:

| Field | Description | Example |
|-------|-------------|---------|
| Pathway ID | Unique identifier | PATH-001 |
| Causal chain | Variable sequence | Gender → Employment History → Default Risk → Approval |
| Effect size | Proportion of total disparity | 40% |
| Classification | Legitimate vs. problematic | Problematic (career breaks penalized) |
| Recommended intervention layer | Data / Model / Output | Data (Pre-Processing) |
| Confidence level | Certainty of causal claim | High (supported by domain knowledge + data) |
| Sensitivity notes | How robust is this finding? | Robust to moderate unmeasured confounding (E-value > 2.5) |

### Decision Logic: When to Proceed vs. Iterate

```mermaid
flowchart TD
    A[Pathway Classification Report Complete] --> B{All major pathways<br/>identified and quantified?}
    B -->|Yes| C{Confidence levels<br/>acceptable?}
    B -->|No| D[Expand analysis:<br/>additional variables,<br/>sensitivity tests]
    D --> A

    C -->|Yes| E[Proceed to Phase 2]
    C -->|No - Low confidence| F{Can we gather<br/>more data?}
    F -->|Yes| G[Collect additional data<br/>or run natural experiments]
    G --> A
    F -->|No| H[Document uncertainty<br/>and proceed with<br/>conservative interventions]
    H --> E

    style E fill:#e8f5e9,stroke:#4CAF50
```

---

## Phase 2: Pre-Processing Interventions — Detailed Workflow

### Purpose
Fix bias at the data source before the model ever sees it. Targets representation gaps, proxy correlations, and label bias identified in Phase 1.

### Inputs
- Pathway Classification Report (from Phase 1)
- Training dataset
- Fairness metric targets

### Process

```mermaid
flowchart TD
    A[Pathway Classification Report] --> B[Filter pathways marked<br/>'Data-level fix needed']

    B --> C{Bias Pattern Type?}

    C -->|Representation<br/>Disparity| D1{Model supports<br/>instance weights?}
    D1 -->|Yes| E1[Instance Reweighting]
    D1 -->|No| E2[Resampling /<br/>Synthetic Generation]

    C -->|Proxy<br/>Discrimination| D2{Interpretability<br/>required?}
    D2 -->|Yes| E3[Disparate Impact<br/>Removal]
    D2 -->|No| E4[Fair Representations<br/>Learning]

    C -->|Label Bias| E5[Prejudice Removal /<br/>Label Massaging]

    C -->|Multiple Types| E6[Combined Approach<br/>- apply techniques sequentially]

    E1 & E2 & E3 & E4 & E5 & E6 --> F[Configure Technique Parameters]

    F --> G[Apply to Training Data]
    G --> H[Evaluate: 3 Dimensions]

    H --> H1[Fairness: primary metrics +<br/>intersectional checks]
    H --> H2[Information Preservation:<br/>accuracy, calibration, rank order]
    H --> H3[Computational Cost:<br/>processing time, memory]

    H1 & H2 & H3 --> I{Acceptable<br/>trade-offs?}

    I -->|Yes| J[Generate Pre-Processing<br/>Evaluation Report]
    I -->|No| K[Adjust parameters<br/>or switch technique]
    K --> F

    J --> L{Residual bias<br/>within tolerance?}
    L -->|Yes| M[Skip to Validation<br/>& Monitoring]
    L -->|No| N[Proceed to Phase 3<br/>with transformed data]

    style A fill:#fff3e0,stroke:#FF9800
    style M fill:#e0f2f1,stroke:#009688
    style N fill:#f3e5f5,stroke:#9C27B0
```

### Technique Selection Matrix

| Bias Pattern | Recommended Technique | When to Use | Key Parameter | Expected Impact |
|-------------|----------------------|------------|---------------|-----------------|
| Representation disparity | Instance Reweighting | Model supports weights; moderate imbalance | Weight cap (2.0-3.0) | Equalizes group influence |
| Representation disparity | SMOTE / Fair-SMOTE | No weight support; severe imbalance | Oversampling ratio | Balances group sizes |
| Proxy discrimination | Disparate Impact Removal | Feature interpretability needed | Repair level (0.0-1.0) | Removes proxy correlation |
| Proxy discrimination | Fair Representations (LFR) | Non-linear proxies; interpretability not critical | Encoding dimensions | Masks protected info in features |
| Label bias | Prejudice Removal | Historical discrimination in labels | Massage proportion | Corrects label distribution |
| Multiple types | Combined sequential | Complex bias with multiple sources | Per-technique params | Addresses multiple pathways |

### Outputs → Pre-Processing Evaluation Report

| Field | Description |
|-------|-------------|
| Techniques applied | List of techniques with parameters |
| Fairness metrics before/after | Primary metric + intersectional breakdown |
| Performance impact | Accuracy, AUC, calibration changes |
| Remaining bias | Residual disparity after pre-processing |
| Computational overhead | Time and memory added to pipeline |
| Recommendation | Proceed to Phase 3 / Skip to monitoring |

---

## Phase 3: In-Processing Interventions — Detailed Workflow

### Purpose
Address bias that survives data-level fixes by embedding fairness constraints directly into model training. Necessary when the model architecture itself learns or amplifies discriminatory patterns.

### Inputs
- Pre-Processing Evaluation Report (from Phase 2)
- Transformed training dataset
- Model architecture specifications
- Acceptable performance degradation threshold

### Process

```mermaid
flowchart TD
    A[Pre-Processing Evaluation Report<br/>+ Transformed Data] --> B[Model Architecture Analysis]

    B --> B1[Model Type<br/>Linear / Tree / Neural / Other]
    B --> B2[Training Approach<br/>Batch / Online / Transfer]
    B --> B3[Technical Constraints<br/>Explainability, latency, etc.]

    B1 & B2 & B3 --> C{Model Family?}

    C -->|Linear Models| D1{Fairness Definition?}
    D1 -->|Demographic Parity| E1[Constraint Optimization<br/>+ preprocessing]
    D1 -->|Equal Opportunity| E2[Constraint Optimization<br/>+ adjusted thresholds]
    D1 -->|Individual Fairness| E3[Similarity-based<br/>Regularization]

    C -->|Tree-Based| D2{Fairness Definition?}
    D2 -->|Demographic Parity| E4[Fair Splitting Criteria]
    D2 -->|Equal Opportunity| E5[Fair Splitting +<br/>Weighted Samples]
    D2 -->|Individual Fairness| E6[Regularized Tree<br/>Induction]

    C -->|Neural Networks| D3{Fairness Definition?}
    D3 -->|Demographic Parity| E7[Adversarial Debiasing]
    D3 -->|Equal Opportunity| E8[Multi-task Learning<br/>with Fairness Head]
    D3 -->|Individual Fairness| E9[Gradient Penalties /<br/>Contrastive Learning]

    E1 & E2 & E3 & E4 & E5 & E6 & E7 & E8 & E9 --> F[Train with Fairness Constraints]

    F --> G[Validate on Held-Out Set]
    G --> H{Performance drop<br/>within threshold?}

    H -->|Yes| I{Fairness improved<br/>significantly?}
    H -->|No| J[Reduce constraint strength<br/>or switch technique]
    J --> F

    I -->|Yes| K[Generate In-Processing<br/>Evaluation Report]
    I -->|No| L[Increase constraint strength<br/>or add regularization]
    L --> F

    K --> M{Residual bias<br/>within tolerance?}
    M -->|Yes| N[Skip to Monitoring]
    M -->|No| O[Proceed to Phase 4]

    style A fill:#e8f5e9,stroke:#4CAF50
    style N fill:#e0f2f1,stroke:#009688
    style O fill:#fce4ec,stroke:#E91E63
```

### Model-Technique Compatibility Matrix

```mermaid
block-beta
    columns 5
    space:1 A["Constraint<br/>Optimization"] B["Adversarial<br/>Debiasing"] C["Fairness<br/>Regularization"] D["Specialized<br/>Algorithms"]

    E["Linear<br/>Models"]:1 F["HIGH"]:1 G["LOW"]:1 H["HIGH"]:1 I["MEDIUM"]:1
    J["Tree-Based<br/>Models"]:1 K["LOW"]:1 L["LOW"]:1 M["MEDIUM"]:1 N["HIGH"]:1
    O["Neural<br/>Networks"]:1 P["MEDIUM"]:1 Q["HIGH"]:1 R["HIGH"]:1 S["MEDIUM"]:1

    style F fill:#c8e6c9
    style H fill:#c8e6c9
    style N fill:#c8e6c9
    style Q fill:#c8e6c9
    style R fill:#c8e6c9
    style G fill:#ffcdd2
    style K fill:#ffcdd2
    style L fill:#ffcdd2
    style I fill:#fff9c4
    style M fill:#fff9c4
    style P fill:#fff9c4
    style S fill:#fff9c4
```

### Outputs → In-Processing Evaluation Report

| Field | Description |
|-------|-------------|
| Technique applied | Method with all hyperparameters |
| Fairness metrics before/after | Comparison on validation set |
| Performance impact | AUC, accuracy, F1 changes |
| Explainability impact | Feature importance stability, SHAP value changes |
| Training overhead | Additional training time, memory |
| Robustness assessment | Sensitivity to hyperparameters, data subsets |
| Recommendation | Proceed to Phase 4 / Skip to monitoring |

---

## Phase 4: Post-Processing Interventions — Detailed Workflow

### Purpose
The last line of defense. Adjusts model predictions without retraining — essential for production systems, black-box models, or situations where retraining is impractical.

### Inputs
- In-Processing Evaluation Report (from Phase 3) or direct model predictions
- Validation data with ground truth
- Business constraints (e.g., target approval rates)
- Deployment constraints (e.g., protected attributes available at inference?)

### Process

```mermaid
flowchart TD
    A[Model Predictions +<br/>Residual Bias Report] --> B{Protected attributes<br/>available at inference?}

    B -->|Yes| C{Fairness Goal?}
    B -->|No| D[Score Transformation<br/>- group-unaware methods]

    C -->|Demographic Parity| E[Group-Specific<br/>Threshold Optimization]
    C -->|Equal Opportunity| F[Calibration +<br/>Threshold Adjustment]
    C -->|Equalized Odds| G[Randomized Threshold<br/>Policy - Hardt et al.]
    C -->|Individual Fairness| H[Score Normalization +<br/>Rank Preservation]

    D & E & F & G & H --> I[Apply Transformation<br/>to Validation Set]

    I --> J{Business constraints<br/>still met?}
    J -->|Yes| K{Fairness targets<br/>achieved?}
    J -->|No| L[Relax fairness constraint<br/>or adjust business target]
    L --> I

    K -->|Yes| M[Configure Monitoring]
    K -->|No| N{Already applied<br/>all relevant methods?}
    N -->|No| O[Add complementary method<br/>e.g., calibration + threshold]
    O --> I
    N -->|Yes| P[Document residual gap<br/>+ escalate to leadership]

    M --> Q[Deploy Post-Processing<br/>Pipeline]
    Q --> R[Generate Post-Processing<br/>Evaluation Report]

    style A fill:#f3e5f5,stroke:#9C27B0
    style R fill:#e0f2f1,stroke:#009688
    style P fill:#fff3e0,stroke:#FF9800
```

### Technique Selection by Scenario

| Scenario | Recommended Approach | Reason |
|----------|---------------------|--------|
| Binary classification, protected attr. known | Group-specific thresholds | Direct, interpretable |
| Probability outputs, calibration gap exists | Platt Scaling per group | Fixes miscalibrated probabilities |
| Black-box model, no protected attr. at inference | Score transformation + uniform threshold | Works without group info |
| Regulatory requirement for equal TPR | Threshold optimization for equal opportunity | Directly targets the constraint |
| Uncertainty near boundary | Rejection option classification | Routes uncertain cases to human review |
| Real-time system, minimal latency budget | Pre-computed lookup table | Zero inference overhead |

### Outputs → Post-Processing Evaluation Report

| Field | Description |
|-------|-------------|
| Techniques applied | Methods with parameters |
| Fairness metrics final | All metrics after full pipeline |
| Performance impact | Cumulative impact across all phases |
| Business metrics | Approval rates, expected loss, customer impact |
| Deployment details | Latency impact, infrastructure needs |
| Monitoring configuration | Alerts, dashboards, drift detection |

---

## Feedback Loops and Iteration

The pipeline is not strictly linear. Several feedback loops ensure continuous improvement:

```mermaid
flowchart LR
    subgraph FORWARD["Forward Pipeline"]
        direction LR
        P1[Phase 1] --> P2[Phase 2] --> P3[Phase 3] --> P4[Phase 4]
    end

    subgraph FEEDBACK["Feedback Loops"]
        direction RL
        FB1[Monitoring detects<br/>fairness regression]
        FB2[New data reveals<br/>unknown pathways]
        FB3[Model update changes<br/>bias profile]
        FB4[Business requirements<br/>or regulations change]
    end

    P4 --> MONITOR[Continuous Monitoring]
    MONITOR --> FB1
    MONITOR --> FB2

    FB1 -->|Re-evaluate| P4
    FB2 -->|Re-analyze| P1
    FB3 -->|Re-train| P3
    FB4 -->|Full review| P1

    style FORWARD fill:#f5f5f5,stroke:#9e9e9e
    style FEEDBACK fill:#fff8e1,stroke:#FFC107
```

### When to Re-Enter the Pipeline

| Trigger | Re-entry Point | Action |
|---------|---------------|--------|
| Fairness metric degrades > 2% | Phase 4 | Adjust thresholds/calibration |
| Fairness metric degrades > 5% | Phase 3 | Retrain with updated constraints |
| New proxy variable discovered | Phase 1 | Re-run causal analysis |
| Population shift detected | Phase 1 | Full pipeline re-evaluation |
| New protected attribute added to scope | Phase 1 | Full pipeline with new attribute |
| Regulatory requirement changes | Phase 1 | Reassess fairness definition |
| Model architecture changes | Phase 3 | Re-select in-processing technique |
| Business constraints change | Phase 4 | Re-optimize thresholds |

---

## Information Flow Summary

```mermaid
graph LR
    subgraph Phase1["Phase 1: Causal Analysis"]
        OUT1[Pathway Classification<br/>Report]
    end

    subgraph Phase2["Phase 2: Pre-Processing"]
        IN2[Pathways needing<br/>data fixes]
        OUT2[Transformed Data +<br/>Evaluation Report]
    end

    subgraph Phase3["Phase 3: In-Processing"]
        IN3[Residual bias report +<br/>clean data]
        OUT3[Fair Model +<br/>Evaluation Report]
    end

    subgraph Phase4["Phase 4: Post-Processing"]
        IN4[Model predictions +<br/>remaining disparities]
        OUT4[Adjusted Predictions +<br/>Final Report]
    end

    subgraph Validation["Validation"]
        VF[Cumulative Assessment<br/>across all dimensions]
    end

    OUT1 --> IN2
    OUT1 -.->|Informs technique selection| IN3
    OUT1 -.->|Informs threshold strategy| IN4
    OUT2 --> IN3
    OUT3 --> IN4
    OUT4 --> VF

    VF -->|Monitoring alerts| Phase1

    style Phase1 fill:#fff3e0,stroke:#FF9800
    style Phase2 fill:#e8f5e9,stroke:#4CAF50
    style Phase3 fill:#f3e5f5,stroke:#9C27B0
    style Phase4 fill:#fce4ec,stroke:#E91E63
    style Validation fill:#e0f2f1,stroke:#009688
```

---

## Key Decision Points

Throughout the pipeline, teams face critical decisions. Here is a consolidated decision reference:

| Decision Point | Options | Criteria for Selection | Risk if Wrong |
|---------------|---------|----------------------|---------------|
| Which causal model to use | Full DAG vs. simplified | Data availability, domain knowledge | Under/over-correction |
| Skip pre-processing? | Yes / No | Bias is not in data; model can compensate | Bias baked into training |
| Technique for proxy removal | DI Removal vs. Fair Representations | Interpretability needs, linearity of proxy | Lose legitimate signal or miss non-linear proxies |
| Skip in-processing? | Yes / No | Pre-processing sufficient; model is black-box | Miss model-amplified bias |
| Fairness constraint strength | Conservative (low λ) vs. aggressive (high λ) | Acceptable performance trade-off | Under-correction or accuracy collapse |
| Skip post-processing? | Yes / No | Bias within tolerance after training | Miss residual disparities |
| Threshold strategy | Group-specific vs. uniform | Legal constraints, attribute availability | Legal exposure or suboptimal fairness |
| When to escalate | Self-serve vs. expert consultation | Complexity, intersectionality, stakes | Inadequate intervention |

### Escalation Decision Tree

```mermaid
flowchart TD
    A[Team applying playbook] --> B{Standard case?<br/>Single axis, known patterns}
    B -->|Yes| C[Team can self-serve<br/>using playbook]
    B -->|No| D{Intersectional effects<br/>or multiple protected attrs?}
    D -->|Yes, but manageable| E[Follow intersectional guide<br/>- Section 05]
    D -->|Complex intersections| F{Legal / regulatory<br/>implications?}
    F -->|No| G[Consult fairness team<br/>for methodology review]
    F -->|Yes| H[Engage legal + fairness<br/>expert team]

    style C fill:#e8f5e9,stroke:#4CAF50
    style E fill:#fff9c4,stroke:#FFC107
    style G fill:#fff3e0,stroke:#FF9800
    style H fill:#ffcdd2,stroke:#E91E63
```
