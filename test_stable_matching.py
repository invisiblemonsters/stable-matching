#!/usr/bin/env python3
"""Tests for stable_matching: known cases, brute-force optimality, CLI bytes."""

import itertools
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

import stable_matching as sm

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "stable_matching.py")


# --- independent reference implementation (deliberately not the library's) ---

def preferred(rank, a, b, size):
    """True if a is strictly preferred to b (None = least preferred)."""
    ra = rank[a] if a is not None else size + 1
    rb = rank[b] if b is not None else size + 1
    return ra < rb


def blocking(assignment, prop, recv):
    """Brute-force blocking pairs: plain loops over every acceptable pair."""
    partner = {r: p for p, r in assignment.items() if r is not None}
    rank_p = {p: {r: i for i, r in enumerate(lst)} for p, lst in prop.items()}
    rank_r = {r: {p: i for i, p in enumerate(lst)} for r, lst in recv.items()}
    out = []
    for p in prop:
        for r in recv:
            if r not in rank_p[p] or p not in rank_r[r]:
                continue
            if not preferred(rank_p[p], r, assignment[p], len(prop[p])):
                continue
            if not preferred(rank_r[r], p, partner.get(r), len(recv[r])):
                continue
            out.append((p, r))
    return out


def block_sizes(n):
    """Every partial injective assignment of n proposers to n receivers."""
    names = [f"r{i}" for i in range(n)]
    for choices in itertools.product(names + [None], repeat=n):
        used = [c for c in choices if c is not None]
        if len(used) != len(set(used)):
            continue
        yield {f"p{i}": choices[i] for i in range(n)}


def all_stable(n, prop, recv):
    return [a for a in block_sizes(n) if not blocking(a, prop, recv)]


def reference_blocks_hr(assignment, prop, recv, capacity):
    rank_p = {p: {h: i for i, h in enumerate(lst)} for p, lst in prop.items()}
    rank_h = {h: {p: i for i, p in enumerate(lst)} for h, lst in recv.items()}
    seats = {h: [] for h in recv}
    for p, h in assignment.items():
        if h is not None:
            seats[h].append(p)
    out = []
    for p in prop:
        for h in recv:
            if h not in rank_p[p] or p not in rank_h[h]:
                continue
            if not preferred(rank_p[p], h, assignment[p], len(prop[p])):
                continue
            if len(seats[h]) < capacity[h]:
                out.append((p, h))
            elif any(not preferred(rank_h[h], q, p, len(recv[h])) for q in seats[h]):
                out.append((p, h))
    return out


# --- tests ---

class TestGaleShapley(unittest.TestCase):
    def test_known_instance(self):
        prop = {
            "alice": ["x", "y", "z"],
            "bob": ["y", "x", "z"],
            "carol": ["x", "y", "z"],
        }
        recv = {
            "x": ["bob", "alice", "carol"],
            "y": ["alice", "bob", "carol"],
            "z": ["alice", "bob", "carol"],
        }
        self.assertEqual(sm.gale_shapley(prop, recv), {"alice": "x", "bob": "y", "carol": "z"})
        self.assertEqual(sm.blocking_pairs(
            {"alice": "x", "bob": "y", "carol": "z"}, prop, recv), [])

    def test_mutual_first_choice(self):
        prop = {"a": ["x"], "b": ["x"]}
        recv = {"x": ["b", "a"]}
        self.assertEqual(sm.gale_shapley(prop, recv), {"a": None, "b": "x"})

    def test_empty_market(self):
        self.assertEqual(sm.gale_shapley({}, {}), {})

    def test_single_pair(self):
        self.assertEqual(sm.gale_shapley({"a": ["x"]}, {"x": ["a"]}), {"a": "x"})

    def test_incomplete_lists_leave_people_unmatched(self):
        prop = {"a": ["x"], "b": ["y"], "c": ["z"]}
        recv = {"x": ["a"], "y": ["a"], "z": ["b"]}
        # c has no mutually acceptable partner, b prefers y but y refuses b.
        self.assertEqual(sm.gale_shapley(prop, recv), {"a": "x", "b": None, "c": None})
        self.assertEqual(list(sm.blocking_pairs({"a": "x", "b": None, "c": None}, prop, recv)), [])

    def test_more_receivers_than_proposers(self):
        prop = {"a": ["x", "y", "z"]}
        recv = {"x": ["a"], "y": ["a"], "z": ["a"]}
        self.assertEqual(sm.gale_shapley(prop, recv), {"a": "x"})

    def test_validation_errors(self):
        with self.assertRaises(sm.MarketError):
            sm.gale_shapley({"a": ["x"]}, {"x": ["a"], "q": ["nobody"]})
        with self.assertRaises(sm.MarketError):
            sm.gale_shapley({"a": ["x", "x"]}, {"x": ["a"]})
        with self.assertRaises(sm.MarketError):
            sm.gale_shapley({"a": "x"}, {"x": ["a"]})


class TestOptimality(unittest.TestCase):
    """Exhaustive comparison against every stable matching of small markets."""

    def test_proposer_optimal_for_random_small_markets(self):
        for seed in range(60):
            n = 2 + seed % 3
            prop, recv = sm.random_market(n, n, seed=seed, completeness=1.0)
            result = sm.gale_shapley(prop, recv)
            self.assertEqual(blocking(result, prop, recv), [])

            stable = all_stable(n, prop, recv)
            self.assertTrue(stable)
            rank_p = {p: {r: i for i, r in enumerate(lst)} for p, lst in prop.items()}
            for p in prop:
                reference = min(
                    (m[p] for m in stable),
                    key=lambda r: rank_p[p][r] if r is not None else len(prop[p]),
                )
                self.assertEqual(result[p], reference, f"seed={seed} proposer={p}")

    def test_incomplete_random_markets_are_stable(self):
        rng = random.Random(7)
        checked = 0
        for seed in range(120):
            n = 1 + seed % 5
            m = 1 + (seed * 3) % 5
            prop, recv = sm.random_market(n, m, seed=seed, completeness=0.5)
            result = sm.gale_shapley(prop, recv)
            self.assertEqual(blocking(result, prop, recv), [], f"seed={seed}")
            targets = [r for r in result.values() if r is not None]
            self.assertEqual(len(targets), len(set(targets)))
            checked += 1
        self.assertEqual(checked, 120)


class TestHospitalResidents(unittest.TestCase):
    def test_capacity_respected(self):
        prop = {"a": ["h1", "h2"], "b": ["h1", "h2"], "c": ["h1", "h2"]}
        recv = {"h1": ["a", "b", "c"], "h2": ["a", "b", "c"]}
        result = sm.hospital_residents(prop, recv, {"h1": 2, "h2": 1})
        self.assertEqual(result, {"a": "h1", "b": "h1", "c": "h2"})
        self.assertEqual(reference_blocks_hr(result, prop, recv, {"h1": 2, "h2": 1}), [])

    def test_everyone_matched_when_seats_available(self):
        prop = {"a": ["h"], "b": ["h"]}
        recv = {"h": ["a", "b"]}
        self.assertEqual(sm.hospital_residents(prop, recv, {"h": 5}), {"a": "h", "b": "h"})

    def test_capacity_bad_values(self):
        prop, recv = {"a": ["h"]}, {"h": ["a"]}
        for bad in (0, -1, 1.5, True, None):
            with self.assertRaises(sm.MarketError):
                sm.hospital_residents(prop, recv, {"h": bad})

    def test_brute_force_small(self):
        prop = {"a": ["h1", "h2"], "b": ["h1"], "c": ["h2", "h1"]}
        recv = {"h1": ["c", "a", "b"], "h2": ["b", "a", "c"]}
        capacity = {"h1": 2, "h2": 1}
        result = sm.hospital_residents(prop, recv, capacity)
        self.assertEqual(reference_blocks_hr(result, prop, recv, capacity), [])

        best = None
        for choices in itertools.product(["h1", "h2", None], repeat=3):
            assignment = dict(zip(["a", "b", "c"], choices))
            if any(target is not None and target not in prop[p]
                   for p, target in assignment.items()):
                continue
            seats = {"h1": 0, "h2": 0}
            for target in assignment.values():
                if target:
                    seats[target] += 1
            if seats["h1"] > 2 or seats["h2"] > 1:
                continue
            if reference_blocks_hr(assignment, prop, recv, capacity):
                continue
            rank_p = {p: {h: i for i, h in enumerate(lst)} for p, lst in prop.items()}
            score = sum(
                rank_p[p].get(assignment[p], 9) for p in assignment
            )
            if best is None or score < best[0]:
                best = (score, assignment)
        rank_p = {p: {h: i for i, h in enumerate(lst)} for p, lst in prop.items()}
        self.assertEqual(sum(rank_p[p].get(result[p], 9) for p in result), best[0])

    def test_resident_optimal_over_seeds(self):
        for seed in range(40):
            rng = random.Random(seed)
            n = 2 + seed % 3
            prop, recv = sm.random_market(n, 2, seed=seed, completeness=1.0)
            capacity = {"r0": rng.randint(1, 3), "r1": rng.randint(1, 3)}
            result = sm.hospital_residents(prop, recv, capacity)
            self.assertEqual(reference_blocks_hr(result, prop, recv, capacity), [], f"seed={seed}")
            for h in capacity:
                holders = [p for p, target in result.items() if target == h]
                self.assertLessEqual(len(holders), capacity[h])


class TestCLI(unittest.TestCase):
    def _run(self, args, stdin=None):
        return subprocess.run(
            [sys.executable, CLI, *args],
            capture_output=True,
            input=stdin,
            cwd=HERE,
        )

    def test_table_output_is_utf8_bytes(self):
        market = {
            "proposers": {"a": ["x", "y"], "b": ["y", "x"]},
            "receivers": {"x": ["a", "b"], "y": ["a", "b"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                json.dump(market, handle)
            done = self._run([path])
        self.assertEqual(done.returncode, 0, done.stderr)
        text = done.stdout.decode("utf-8")
        self.assertIn(b"stable: yes", done.stdout)
        self.assertIn("a", text)
        self.assertNotIn(b"\r\n", done.stdout)
        self.assertTrue(text.endswith("\n"))

    def test_json_output_and_exit_code(self):
        market = {
            "proposers": {"a": ["x"]},
            "receivers": {"x": ["a"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                json.dump(market, handle)
            done = self._run([path, "--json"])
        payload = json.loads(done.stdout.decode("utf-8"))
        self.assertEqual(payload, {"matching": {"a": "x"}, "stable": True, "blocking_pairs": []})
        self.assertEqual(done.returncode, 0)

    def test_random_mode_and_capacity(self):
        done = self._run(["--random", "4", "--seed", "3", "--capacity", "2", "--json"])
        self.assertEqual(done.returncode, 0, done.stderr)
        payload = json.loads(done.stdout.decode("utf-8"))
        self.assertTrue(payload["stable"])
        counts = {}
        for target in payload["matching"].values():
            if target:
                counts[target] = counts.get(target, 0) + 1
        self.assertTrue(all(v <= 2 for v in counts.values()))

    def test_invalid_json_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write("{not json")
            done = self._run([path])
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"invalid JSON", done.stderr)
        self.assertEqual(done.stdout, b"")

    def test_missing_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                json.dump({"proposers": {}}, handle)
            done = self._run([path])
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"receivers", done.stderr)


if __name__ == "__main__":
    unittest.main()
