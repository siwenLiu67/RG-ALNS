"""Tests for the 0-1 knapsack DP solver used in recoverability analysis."""

import pytest
from src.recoverability.knapsack_recovery import _solve_knapsack_dp


class TestKnapsackDP:
    def test_empty_items(self):
        val, sel = _solve_knapsack_dp([], 100)
        assert val == 0
        assert sel == set()

    def test_zero_capacity(self):
        items = [(0, 10, 5), (1, 20, 10)]
        val, sel = _solve_knapsack_dp(items, 0)
        assert val == 0
        assert sel == set()

    def test_single_item_fits(self):
        items = [(0, 10, 5)]
        val, sel = _solve_knapsack_dp(items, 10)
        assert val == 10
        assert sel == {0}

    def test_single_item_too_heavy(self):
        items = [(0, 10, 15)]
        val, sel = _solve_knapsack_dp(items, 10)
        assert val == 0
        assert sel == set()

    def test_two_items_exact_fit(self):
        items = [(0, 10, 5), (1, 20, 10)]
        val, sel = _solve_knapsack_dp(items, 15)
        assert val == 30
        assert sel == {0, 1}

    def test_two_items_pick_best(self):
        # Cannot take both (weight 7+5=12 > 10), pick higher value
        items = [(0, 10, 7), (1, 20, 5)]
        val, sel = _solve_knapsack_dp(items, 10)
        assert val == 20
        assert sel == {1}

    def test_two_items_equal_value_pick_lighter(self):
        items = [(0, 20, 8), (1, 20, 5)]
        val, sel = _solve_knapsack_dp(items, 10)
        assert val == 20
        # Both give same value, either is acceptable
        assert len(sel) == 1

    def test_zero_weight_items_always_taken(self):
        items = [(0, 5, 0), (1, 10, 3), (2, 7, 0)]
        val, sel = _solve_knapsack_dp(items, 5)
        # Zero-weight items (0 and 2) are always taken: value 5+7=12
        # Item 1 (v=10,w=3) also fits: total 22
        assert 0 in sel
        assert 2 in sel
        assert 1 in sel
        assert val == 22

    def test_multiple_items_larger_capacity(self):
        items = [
            (0, 10, 5),
            (1, 15, 8),
            (2, 20, 12),
            (3, 25, 15),
        ]
        val, sel = _solve_knapsack_dp(items, 25)
        # Best should be taking items 2 and 3: 20+25=45, weight=12+15=27 > 25 ✗
        # Try all combos manually:
        # 0+1+2: 10+15+20=45, weight=5+8+12=25 ✓ → 45
        # 0+1+3: 10+15+25=50, weight=5+8+15=28 > 25
        # 0+2+3: 10+20+25=55, weight=5+12+15=32 > 25
        # 1+2+3: 15+20+25=60, weight=8+12+15=35 > 25
        assert val == 45
        assert sel == {0, 1, 2}

    def test_capacity_much_larger_than_weights(self):
        items = [(0, 10, 5), (1, 20, 10)]
        val, sel = _solve_knapsack_dp(items, 1000)
        assert val == 30
        assert sel == {0, 1}

    def test_knapsack_deterministic(self):
        items = [(0, 10, 5), (1, 20, 10), (2, 30, 15)]
        val1, sel1 = _solve_knapsack_dp(items, 20)
        val2, sel2 = _solve_knapsack_dp(items, 20)
        assert val1 == val2
        assert sel1 == sel2

    def test_tie_breaking(self):
        # When two items have equal value but different weights, DP should
        # prefer the combination that yields max value.
        items = [(0, 15, 8), (1, 15, 6)]
        val, sel = _solve_knapsack_dp(items, 10)
        # With capacity 10: both take value 15, both fit individually
        # Both can't fit together (8+6=14 > 10)
        assert val == 15
        assert len(sel) == 1
