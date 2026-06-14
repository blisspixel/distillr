"""Tests for distill.eval.stats (deterministic small-sample bootstrap)."""

from distill.eval.stats import bootstrap_mean_ci


def test_empty_is_zero_band():
    assert bootstrap_mean_ci([]) == (0.0, 0.0)


def test_single_value_is_zero_width_at_that_value():
    assert bootstrap_mean_ci([0.7]) == (0.7, 0.7)


def test_identical_values_give_zero_width_band():
    # The degeneracy the min-N rule exists to guard: identical points look
    # certain. CI collapses to the value; the caller must not trust width alone.
    low, high = bootstrap_mean_ci([0.55, 0.55, 0.55, 0.55])
    assert low == 0.55 and high == 0.55


def test_band_brackets_the_mean_and_is_ordered():
    values = [0.2, 0.4, 0.6, 0.8, 1.0, 0.5, 0.3, 0.7]
    low, high = bootstrap_mean_ci(values)
    mean = sum(values) / len(values)
    assert low <= mean <= high
    assert low < high  # genuine spread -> non-degenerate band


def test_deterministic_across_calls():
    # Fixed seed -> identical bounds every call (reproducible eval / CI).
    values = [0.1, 0.9, 0.3, 0.7, 0.5, 0.6]
    assert bootstrap_mean_ci(values) == bootstrap_mean_ci(values)


def test_wider_spread_gives_wider_band():
    tight = bootstrap_mean_ci([0.5, 0.5, 0.5, 0.5, 0.5, 0.51, 0.49, 0.5])
    wide = bootstrap_mean_ci([0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    assert (wide[1] - wide[0]) > (tight[1] - tight[0])
