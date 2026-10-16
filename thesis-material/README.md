# thesis-material

Raw material for four chapters: (1) Data, (2) Prediction, (3) Autoscaling, (4) Results vs Dogani. No prose.

- `facts/01_data.md`, `02_prediction.md`, `03_autoscaling.md`, `04_results_vs_dogani.md`: one bullet per number, setting or decision, each with its source (docs/decisions.md entry or a results file). Sections within each file follow the chapter outline.
- `tables/`: LaTeX snippets (booktabs; wide ones in `\resizebox`; need `\usepackage{booktabs,graphicx}`).
  - `table8_accuracy.tex`: federated vs central, BiGRU vs LSTM, ours and Dogani's Table 8
  - `table9_dm_test.tex`: Diebold-Mariano test
  - `fl_bytes_breakeven.tex`: bytes per round, totals, break-even rounds
  - `sim4a_metrics.tex`, `sim4a_fair_podsmin1.tex`, `sim4a_fair_podsmin5.tex`: step 4A simulation vs Dogani's Table 11
  - `live4b_vs_dogani_table11.tex`: step 4B live run vs Dogani's Table 11
- `figures/`: result plots copied from `results/`.
  - `prediction/`, `autoscaling_sim/`, `autoscaling_live/`: PNG (matplotlib output at 130 dpi; the vector source data is not in git, so no PDF exists)
  - `cpu_controller/`: PDF, earlier reactive-vs-proactive CPU controller runs (not part of the four chapters)
- `dogani_differences.md`: inconsistencies and gaps in Dogani & Khunjush (2024), with page/table numbers as recorded in docs/decisions.md.

## Not included

- Plots of the FIFA requests per minute, and of real vs synthetic traces (node 0 and 1) exist only in the git-ignored `data/` folder of the other worktree (`Autoscaling-fifa/data/`), which I left untouched. To add them, copy `fifa_requests_per_minute_days5-92.png` and `synthetic/node_00.png`, `node_01.png` from there, or re-run `scripts/plot_fifa_workload.py` and `scripts/synthetic_traces.py`.
- The paper itself is not in the repo, so page numbers were not re-checked.

## Things to verify before quoting

- Resolved: the real full-trace maximum is 229,426 req/min; 154k (153,878) was the maximum of the one-week test window, and decisions.md 2.2 now says so. The 7.8 million Fisk figure is still unverified in saved files.
- decisions.md 4A.2 says scale factors 0.42 to 2.44; table11.md says 0.4157 to 2.4404 (same, rounded).
- `facts/03_autoscaling.md` section 3.4 uses numbers from the project CLAUDE.md (untracked), not from a committed file.
