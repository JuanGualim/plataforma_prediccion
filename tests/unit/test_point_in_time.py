import numpy as np
import pandas as pd

from mlplatform.features.point_in_time import EventStream, open_count, to_micros

T = pd.Timestamp("2025-03-01 12:00", tz="UTC")


def at(*offsets_h: float) -> np.ndarray:
    return to_micros(pd.Series([T + pd.Timedelta(hours=h) for h in offsets_h]))


def test_window_excludes_the_instant_itself_and_includes_the_old_edge() -> None:
    events = EventStream.from_series(
        pd.Series([T - pd.Timedelta(hours=2), T - pd.Timedelta(hours=1), T])
    )

    assert events.count(at(0), pd.Timedelta(hours=2)).tolist() == [2]
    assert events.count(at(0), pd.Timedelta(hours=1)).tolist() == [1]
    assert events.count(at(0.001), pd.Timedelta(hours=2)).tolist() == [2]  # el borde viejo sale


def test_unknown_events_are_ignored() -> None:
    events = EventStream.from_series(pd.Series([T - pd.Timedelta(hours=1), pd.NaT]))

    assert events.count(at(1), pd.Timedelta(days=1)).tolist() == [1]


def test_mean_falls_back_to_default_with_too_few_events() -> None:
    times = pd.Series([T - pd.Timedelta(hours=h) for h in (3, 2, 1)])
    events = EventStream.from_series(times, pd.Series([1.0, 0.0, 0.0]))

    assert events.mean(at(0), pd.Timedelta(hours=5), 3, 0.5).tolist() == [1 / 3]
    assert events.mean(at(0), pd.Timedelta(hours=5), 4, 0.5).tolist() == [0.5]
    assert events.mean(at(0), pd.Timedelta(hours=1.5), 1, 0.5).tolist() == [0.0]


def test_open_count_is_a_queue_length() -> None:
    started = pd.Series([T - pd.Timedelta(hours=h) for h in (5, 4, 3)])
    ended = pd.Series([T - pd.Timedelta(hours=2), pd.NaT, T + pd.Timedelta(hours=1)])

    assert open_count(started, ended, at(-4.5, -1, 0, 2)).tolist() == [1, 2, 2, 1]


def test_vectorized_count_matches_a_naive_loop() -> None:
    rng = np.random.default_rng(0)
    times = pd.Series(T + pd.to_timedelta(rng.integers(0, 10 * 24 * 3600, 500), unit="s"))
    instants = pd.Series(T + pd.to_timedelta(rng.integers(0, 10 * 24 * 3600, 50), unit="s"))
    window = pd.Timedelta(hours=24)

    fast = EventStream.from_series(times).count(to_micros(instants), window)

    naive = [((times >= t - window) & (times < t)).sum() for t in instants]
    assert fast.tolist() == naive
