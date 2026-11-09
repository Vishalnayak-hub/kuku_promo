# Quality report

## Hard checks (every promo, no judgement involved)

| Check | Result | Failures |
|---|---|---|
| length_20_60s | PASS | 0 |
| segments_inside_episode | PASS | 0 |
| segments_ordered_no_overlap | PASS | 0 |
| no_cut_through_a_spoken_line | PASS | 0 |
| hook_within_3s | PASS | 0 |
| quotes_exist_in_source | PASS | 0 |
| distinct_within_episode | PASS | 0 |
| ranked_by_score | PASS | 0 |
| unique_ids | PASS | 0 |

## Agreement with the show's own cliffhanger notes

Read from the next episode's CONTINUITY NOTES; n = 1 episodes; hit = the last 15s of the promo contain >= 40% of the note's rare key words.

| Method | Top-1 | Any of top-3 |
|---|---|---|
| this tool | 1/1 | 1/1 |
| baseline: the episode's final window | 1/1 | - |
| baseline: random clean-cut windows (expected) | 0.6/1 | - |