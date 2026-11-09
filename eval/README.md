# eval/ - label files for the quality checks (timestamps only, no screenplay text)

| File | Source | Used for |
|---|---|---|
| `human_picks.csv` | the author's own five human-reviewed windows from v1 (`final_ranked_promo_shortlist.csv`) | agreement check (`--eval-dir eval`) |
| `human_rejects.csv` | the author's EP46 rejection case | negative example |
| `v1_baseline.csv` | what the v1 pipeline ranked best per episode (`deduplicated_candidates.csv`) | v1 comparison |

They only make sense for the original 50-episode pack. The cliffhanger-note check needs no files: it reads each episode's
`CONTINUITY NOTES` and works on any input that has them.
