<h1 align="center">AI Ethics — Practical Fairness for Data Scientists</h1>

<p align="center">
  <strong>Translating abstract ethical principles into actionable, measurable fairness practices for machine learning systems.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/MLflow-tracking-0194e2?logo=mlflow&logoColor=white" alt="MLflow">
  <img src="https://img.shields.io/badge/scikit--learn-ML-f7931e?logo=scikitlearn&logoColor=white" alt="scikit-learn">
  <img src="https://img.shields.io/badge/tests-35_passing-2ea44f" alt="Tests">
  <img src="https://img.shields.io/badge/Turing_College-specialization-6a5acd" alt="Turing College">
</p>

---

## Overview

Projects developed during the **AI Ethics Specialization** at Turing College. Each corresponds to
one module and addresses a distinct challenge in the design, development, and deployment of AI
systems. Together they build a progression from **conceptual auditing to production-ready fairness
tooling** — the practical side of the accountability and governance questions I want to research.

## Modules

| Module | Question | Deliverable |
|---|---|---|
| **1 — Audit** | Can we *detect and measure* bias? | Fairness Audit Framework |
| **2 — Intervene** | Can we *reduce* bias? | Fairness Intervention Playbook |
| **3 — Implement** | Can we *scale* fairness across an organization? | Fairness Implementation Playbook |
| **Final** | Can we *integrate* it all? | Automated Fairness Pipeline |

### Module 1 — Fairness Audit Framework
A playbook for systematically evaluating AI systems for bias: a glossary of fairness concepts, an
executive summary for stakeholders, a technical audit report, and an implementation guide.

### Module 2 — Fairness Intervention Playbook
Unifies four intervention approaches — causal analysis, pre-processing, in-processing, and
post-processing — with integration strategies, case studies, validation frameworks, intersectional
fairness, and adaptability guidelines.

### Module 3 — Fairness Implementation Playbook
An end-to-end methodology for deploying fairness across AI systems and organizations, aimed at
director-level stakeholders and cross-functional teams.

### Final Project — Fairness Pipeline Development Toolkit
A **configuration-driven, automated fairness pipeline** that integrates measurement, data
engineering, and model training into a single orchestrated system:
- **`config.yml`** — declarative definition of the entire workflow.
- **`run_pipeline.py`** — three-step orchestrator: Baseline Measurement → Transform & Train → Final Validation (PASS/FAIL).
- **`demo.ipynb`** — interactive demonstration.
- **MLflow integration** — full experiment traceability (metrics, artifacts, configuration).
- **35 automated tests** — unit, functional, and end-to-end.

## Tech Stack

Python · scikit-learn · MLflow · pytest · Jupyter.
