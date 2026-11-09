# Review notes on the outputs (AI-assisted reading, text only)

Read by Claude from the screenplay text of the final run (`submission/raw_outputs/`). **This is not an editor's judgement and no video was
watched.** Re-read a sample yourself before quoting any of it; edit this file with your own verdicts.

## Top-15 "post first" list - quick read

* **Solid (11):** #1 EP28 0:00-0:48, #3 EP45, #4 EP36 (cuts on "What wedding?" before the answer), #5 EP35, #7 EP43 0:24-0:56 (cuts on "No..." before "Read the names."),
  #8 EP12, #9 EP01 0:46-1:21, #10 EP27, #12 EP25, #13 EP32, #15 EP36 (ep-end).
* **Borderline (4):** #2 EP24 and #14 EP34 end on a question whose answer is trivial ("No, my lady." / "Yes, Your Honor.");
  #6 EP24 ends one beat before the rest of the same insult; #11 EP24 is a weak episode-end beat.
* **Clear failures:** none seen in the top 15.

## Failure modes seen across all 134 promos

1. **Loaded vs procedural question.** The cliffhanger score rewards an unanswered question, but cannot tell "What wedding?" (answer is a bombshell)
   from "Prudence. You served beside the accused?" (answer is "Yes."). The line withheld after the cut is shown precisely so a human or LLM can tell.
2. **False resolution penalty.** EP35 (1:51-2:37) is flagged "ends on an answer" although the answer is the reveal (3 promos carry this flag: EP35, EP44, EP16).
3. **Forced episode-ending cut can be weak.** EP47 ends "I accept, Your Grace." (flagged as closure) and EP08 ends on "Perhaps I was wrong." (not flagged). They rank 85th and 96th of 134.
4. **Some episodes have no strong promo:** the bottom three of 134 are EP07 (x2) and EP39 (long silent stretches, no cliffhanger signal). 45 of 134 promos carry at least one flag.
5. **Visual cliffhangers are only guessed** from camera/action text (a narrow regex), so an image-only ending is easy to miss.
6. **Backstory:** the top picks come mostly from episodes 24-45; a new viewer needs context the clip may not give. No early-episode bias is applied.
7. **Disagreement with the author's human pick on EP01:** the tool's top-1 is 0:46-1:21 (a confrontation); the human preferred 0:00-0:40 (visual
   wedding opening, no spoken hook for 11 s). That is a real editorial difference, not just an error.

## Checks and their honest weight

| Check | Result | How much to trust it |
|---|---|---|
| 9 hard checks on every promo | 9/9 pass | Structural only: length, cut points, hook timing, quote fidelity, distinctness. Says nothing about taste |
| Show's own cliffhanger notes (n=10) | top-1 1/10, top-3 6/10; "final window" 6/10; random 2.0/10 | Tiny, and in-sample after the documented change |
| Author's human picks (5 windows, 4 episodes) | 4/5 hit; random 2.9/5; v1 5/5 | Weak: v1's candidate pool contained these picks, and 20-60 s windows overlap a 40-60 s pick often by chance |
