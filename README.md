# ASCAL-Guided Planning Framework

A general framework for solving planning tasks under unknown action models.
The framework interleaves three components:

- **ASCAL** — the learning module, which maintains *sound* (M_S) and *complete* (M_C) approximations of the hidden action model at all times.
- **Planner** — uses M_S and M_C to generate execution instructions and refine them as new demonstrations arrive.
- **Simulator** — the black-box oracle: validates plans and returns demonstrations that update the learned models.

At every iteration the agent queries ASCAL for the current models, invokes the planner to obtain a set of execution instructions, executes them in the simulator, and feeds the resulting demonstrations back to ASCAL and the planner.
The loop terminates when a solution is certified or no further progress is possible.

---

## Planning modes

Two instantiations of the framework are defined in the paper:

| Mode | Description | Status |
|------|-------------|--------|
| **Model-based planning** | The planner searches over the learned models (M_S, M_C) and uses the simulator as a validation oracle. Plans found in M_S are immediately valid in the true model; M_C drives optimistic exploration. | **Implemented — `experiments/KEPS2026`** |
| **Model-guided interaction** | Search is performed directly over the simulator (A*-style), guided by an admissible heuristic derived from M_C. | Planned — future release |

This repository currently contains the experiment code and pre-computed results for the **model-based planning** mode, as reported in:

> **Planning while Learning with Anytime Sound and Complete Models**  
> Pablo Copete, Diego Aineto, Eva Onaindia, Enrico Scala. KEPS 2026.

---

## Repository layout

```
ascal/                          ASCAL learning module (git submodule → companion repo)
benchmarks/                     PDDL benchmark domains and problems
│   blocks/                     20 problems
│   driverlog/                  20 problems
│   miconic/                    20 problems
│   satellite/                  20 problems
experiments/
│   KEPS2026/                   Model-based planning — KEPS 2026 paper
│   │   scripts/                Experiment drivers (see below)
│   │   notebooks/              results_ascal_vs_blind.ipynb — paper figures
│   │   media/                  Final figures (PDF + PNG) as they appear in the paper
│   │   tests/                  Smoke tests
│   │   results/
│   │   │   results_ascal_no_restart/   Logs — carry-state variant
│   │   │   results_ascal_restart/      Logs — restart-on-negative-demo variant
│   │   │   results_blind/              Logs — blind UCS baseline
environment.yml                 Conda environment spec (installs ASCAL from the submodule)
pyproject.toml                  Python package metadata / dependency list
```

New experiments implementing future framework modes (e.g. model-guided interaction) will each get their own folder under `experiments/`.

---

## Setup

### 1. Clone with submodule

```bash
git clone --recurse-submodules <this-repo-url>
cd KEPS
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

### 2. Create the conda environment

```bash
conda env create -f environment.yml
conda activate ascal_env
```

`environment.yml` installs ASCAL directly from the `ascal/` submodule (`-e ./ascal`) so the exact code used in the experiments is always in view.

---

## Reproducing the KEPS 2026 results

All commands below are run from the **repository root**.
Scripts resolve benchmarks from `benchmarks/` and write logs inside `experiments/KEPS2026/`.

### Run the model-based planning experiments

Two carry-state variants are provided:

```bash
bash experiments/KEPS2026/scripts/run_ascal_no_restart_all.sh   # logs → experiments/KEPS2026/results/results_ascal_no_restart/
bash experiments/KEPS2026/scripts/run_ascal_restart_all.sh      # logs → experiments/KEPS2026/results/results_ascal_restart/
```

Each script runs all 80 problems (4 domains × 20 problems) in parallel (default 5 jobs).
Override with `MAX_JOBS=8 bash experiments/KEPS2026/scripts/run_ascal_no_restart_all.sh`.

### Run the blind UCS baseline

```bash
bash experiments/KEPS2026/scripts/run_blind_all.sh              # logs → experiments/KEPS2026/results/results_blind/
```

### Regenerate the paper figures

```bash
cd experiments/KEPS2026/notebooks
jupyter nbconvert --to notebook --execute results_ascal_vs_blind.ipynb
```

Figures are written to `experiments/KEPS2026/media/` (PDF and PNG).

Override the default results paths at runtime:
```bash
RESULTS_ROOT=/custom/path bash experiments/KEPS2026/scripts/run_ascal_no_restart_all.sh
```

---

## Scripts overview (KEPS 2026)

| File | Purpose |
|------|---------|
| `experiments/KEPS2026/scripts/loop_ascal_no_restart.py` | Model-based planning loop — carry-state (no restart on negative demo). One problem per run. |
| `experiments/KEPS2026/scripts/loop_ascal_restart.py` | Model-based planning loop — restart-on-negative-demo. One problem per run. |
| `experiments/KEPS2026/scripts/run_ascal_no_restart_all.sh` | Parallel driver for `loop_ascal_no_restart.py`. |
| `experiments/KEPS2026/scripts/run_ascal_restart_all.sh` | Parallel driver for `loop_ascal_restart.py`. |
| `experiments/KEPS2026/scripts/run_ucs_baseline.py` | Blind UCS on ground-truth PDDL. One problem per invocation. |
| `experiments/KEPS2026/scripts/run_blind_all.sh` | Parallel driver for `run_ucs_baseline.py`. |
| `experiments/KEPS2026/scripts/ucs_baseline_core.py` | Core UCS implementation and plan replay. |
| `experiments/KEPS2026/scripts/aggregate_results_server.py` | Parse `.log` files into CSV / summary table. |

---

## Environment notes

- Python 3.11, `unified-planning>=1.3.0`, `up-fast-downward` (bundles Fast Downward), `numpy`, `matplotlib`, and the other pip dependencies in `environment.yml`.
- The planner inside the loop scripts is **Fast Downward** via the `up-fast-downward` package — no separate system-wide FD install required.
- ASCAL lives in the `ascal/` submodule (see [pablocopete/ascal](https://github.com/pablocopete/ascal)).
