from __future__ import annotations

from src.common import default_track_count, target_track_duration
from src.prompt_compiler import compile_prompts


def test_default_45_minute_plan_is_multiple_tracks():
    assert default_track_count(45) == 12
    assert 3 <= default_track_count(10) <= 24


def test_offline_plan_has_exact_requested_track_count_and_distinct_seeds():
    plan = compile_prompts(
        "rainy Tokyo cafe at midnight", None,
        ["felt piano", "tape hiss"], n_tracks=6, target_minutes=30, offline=True,
    )
    assert len(plan["tracks"]) == 6
    assert len({track["seed"] for track in plan["tracks"]}) == 6
    assert all(180 <= track["duration_sec"] <= 240 for track in plan["tracks"])


def test_target_track_duration_accounts_for_crossfade():
    assert target_track_duration(45, 12, crossfade_sec=4) == 229
