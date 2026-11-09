from promo_finder.candidates import EpisodeIndex, generate
from promo_finder.parse import parse_text
from promo_finder.scoring import score
from promo_finder.select import choose_picks, best_episode_ending, pick_distinct, overlap_ratio


def _mk(lines, dur=70.0, extra=""):
    """Tiny synthetic episode: lines = [(start, end, speaker, tags, text)]."""
    out = ["EPISODE NUMBER: Episode 1", "", "SCENE 01", "Scene heading: INT. X - DAY",
           "Scene start: 00:00.00", f"Scene end: 01:{dur - 60:05.2f}", ""]
    for s, e, sp, tags, text in lines:
        out += [f"**{sp} ({tags}):**", f"Start: (00:{s:05.2f}) | End: (00:{e:05.2f})", f'"{text}"', ""]
    out.append(extra)
    return parse_text("\n".join(out), "e.txt")


def _chat(n=24, step=3.0, last_text="Where is he?"):
    rows, t = [], 1.0
    for i in range(n):
        sp = "ANNA" if i % 2 == 0 else "BEN"
        text = last_text if i == n - 1 else f"Line number {i} of the quarrel."
        rows.append((t, t + 2.0, sp, "Cold, Furious", text))
        t += step
    return rows


def test_invariants_on_sample(sample_episodes):
    for ep in sample_episodes:
        ix = EpisodeIndex(ep)
        cands = generate(ep, ix=ix)
        assert cands
        for c in cands:
            assert 20 - 1e-6 <= c.duration <= 60 + 1e-6
            assert not ix.straddles(c.start) and not ix.straddles(c.end)
            assert c.opener.start - c.start <= 3.0 + 1e-6


def test_never_splits_a_continued_sentence():
    rows = _chat()
    rows[10] = (rows[10][0], rows[10][1], "ANNA", "Cold", "If he has nothing to hide...")
    rows[11] = (rows[10][1] + 0.1, rows[10][1] + 2.0, "ANNA", "Cold", "...let them search.")
    ep = _mk(rows)
    ix = EpisodeIndex(ep)
    first, second = ix.dialogue[10], ix.dialogue[11]
    for c in generate(ep, ix=ix):
        assert c.closer is not first      # cannot end between the two halves
        assert c.opener is not second     # cannot start on the continuation


def test_unanswered_question_beats_closure():
    q = _mk(_chat(last_text="Where is he?"))
    done = _mk(_chat(last_text="Thank you, goodbye."))
    best = {}
    for name, ep in (("q", q), ("done", done)):
        ix = EpisodeIndex(ep)
        cands = [c for c in generate(ep, ix=ix) if abs(c.end - ix.dialogue[-1].end) < 3 and c.duration > 25]
        assert cands
        best[name] = max(score(ix, c) for c in cands) if False else max((score(ix, c) for c in cands), key=lambda s: s.parts["cliffhanger"])
    assert best["q"].parts["cliffhanger"] > best["done"].parts["cliffhanger"] + 5
    assert any("resolution" in f for f in best["done"].flags)


def test_interrupted_line_is_a_cliffhanger():
    ep = _mk(_chat(last_text="They have been\u2014"))
    ix = EpisodeIndex(ep)
    cands = [c for c in generate(ep, ix=ix) if abs(c.end - ix.dialogue[-1].end) < 3]
    top = max((score(ix, c) for c in cands), key=lambda s: s.parts["cliffhanger"])
    assert "mid-sentence" in top.cliff_label


def test_scoring_is_deterministic(sample_episodes):
    ep = sample_episodes[0]
    ix1, ix2 = EpisodeIndex(ep), EpisodeIndex(ep)
    a = [score(ix1, c).total for c in generate(ep, ix=ix1)]
    b = [score(ix2, c).total for c in generate(ep, ix=ix2)]
    assert a == b


def test_scores_stay_in_bounds(sample_episodes):
    for ep in sample_episodes:
        ix = EpisodeIndex(ep)
        for c in generate(ep, ix=ix):
            s = score(ix, c)
            assert 0 <= s.total <= 100
            assert all(0 <= v for v in s.parts.values())


def test_pick_distinct_respects_overlap(sample_episodes):
    ep = sample_episodes[0]
    ix = EpisodeIndex(ep)
    scored = [score(ix, c) for c in generate(ep, ix=ix)]
    picks = pick_distinct(scored, 3, 0.25)
    for i, a in enumerate(picks):
        for b in picks[i + 1:]:
            assert overlap_ratio(a, b) <= 0.25


def test_episode_ending_cut_is_always_offered(sample_episodes):
    ep = sample_episodes[0]
    ix = EpisodeIndex(ep)
    scored = [score(ix, c) for c in generate(ep, ix=ix)]
    end = best_episode_ending(scored, ix.duration)
    assert end is not None and end.cand.end >= ix.duration - 1.0
    picks = choose_picks(pick_distinct(scored, 6), end, 3)
    assert any(p is end for p in picks)

def test_interrupted_line_with_dramatic_reaction_is_supported_cliffhanger():
    rows = _chat(last_text="They have been—")
    ep = _mk(rows)

    from promo_finder.models import ACTION, Event

    last = max(ep.dialogue, key=lambda d: d.end)

    ep.events.append(Event(
        idx=max(e.idx for e in ep.events) + 1,
        kind=ACTION,
        start=last.end + 0.1,
        end=last.end + 1.2,
        text="She collapses back onto the pillows, coughing violently.",
        scene=last.scene,
    ))

    ep.scenes[0].end = max(
        ep.scenes[0].end,
        last.end + 1.2
    )

    ix = EpisodeIndex(ep)

    from promo_finder.candidates import Candidate

    cand = Candidate(
        ep.number,
        0.0,
        last.end + 1.2,
        ix.dialogue[0],
        last,
    )

    result = score(ix, cand)

    assert "dramatic reaction" in result.cliff_label

    assert not any(
        "likely accidental cut" in flag
        for flag in result.flags
    )


def test_same_speaker_continuation_is_not_rewarded_as_cliffhanger():
    rows = _chat(last_text="They have been—")

    last = rows[-1]

    rows.append((
        last[1] + 0.1,
        last[1] + 1.5,
        last[2],
        "Cold",
        "...working together all along."
    ))

    ep = _mk(rows)
    ix = EpisodeIndex(ep)

    from promo_finder.candidates import Candidate

    first = ix.dialogue[-2]

    cand = Candidate(
        ep.number,
        0.0,
        first.end,
        ix.dialogue[0],
        first,
    )

    result = score(ix, cand)

    assert any(
        "same speaker continues" in flag
        for flag in result.flags
    )



def test_context_dependent_opener_is_penalized():
    rows = _chat(n=24)

    # Make the SECOND dialogue line context-dependent.
    rows[1] = (
        rows[1][0],
        rows[1][1],
        rows[1][2],
        rows[1][3],
        "What about him?"
    )

    ep = _mk(rows)
    ix = EpisodeIndex(ep)

    cand = next(
        c for c in generate(ep, ix=ix)
        if c.opener is ix.dialogue[1]
    )

    # Verify that the test data is correct.
    assert cand.opener.text == "What about him?"

    prev = ix.line_before(cand.start)

    assert prev is not None
    assert cand.start - prev.end < 2.0
    assert prev.scene == cand.opener.scene

    from promo_finder import textcues as tc

    assert tc.CONTEXT_DEPENDENT_OPENER.search(
        cand.opener.text
    )

    result = score(ix, cand)

    assert any(
        "context-dependent opener" in flag
        for flag in result.flags
    )
def test_clear_opening_is_not_penalized_as_context_dependent():
    rows = _chat(n=24, last_text="Where is he?")

    rows[0] = (
        rows[0][0],
        rows[0][1],
        "ANNA",
        "Furious",
        "Your father betrayed the kingdom!"
    )

    ep = _mk(rows)
    ix = EpisodeIndex(ep)

    cand = next(
        c for c in generate(ep, ix=ix)
        if c.opener is ix.dialogue[0]
    )

    result = score(ix, cand)

    assert not any(
        "context-dependent opener" in flag
        for flag in result.flags
    )

    