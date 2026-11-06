#!/usr/bin/env python3
"""Stable matching: Gale-Shapley for one-to-one and hospital/residents markets.

Two solvers, both deferred-acceptance:

* ``gale_shapley``        -- one-to-one stable marriage (unequal sides and
                            incomplete preference lists are allowed).
* ``hospital_residents``  -- many-to-one version where each receiver accepts
                            up to a capacity.

Both return a dict mapping the proposing side to a receiver (or ``None`` when
unmatched). Matching is proposer-optimal: no stable matching gives any
proposer a receiver they prefer to the one returned here.

Run ``python stable_matching.py --help`` for the command line interface.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import deque

__all__ = [
    "gale_shapley",
    "hospital_residents",
    "blocking_pairs",
    "blocking_pairs_capacity",
    "validate_market",
]


class MarketError(ValueError):
    """Raised when a preference market is malformed."""


def _as_list(name, value, side):
    if not isinstance(value, (list, tuple)):
        raise MarketError(f"{side} preference list for {name!r} must be a list")
    seen = set()
    for other in value:
        if not isinstance(other, str):
            raise MarketError(f"{side} preference for {name!r} contains a non-string")
        if other in seen:
            raise MarketError(f"{side} {name!r} ranks {other!r} more than once")
        seen.add(other)
    return list(value)


def validate_market(proposer_prefs, receiver_prefs):
    """Validate and normalize a two-sided market.

    Every name used on either side must exist as a key on that side, and no
    side may rank a partner twice. Unknown names are rejected rather than
    silently ignored -- a typo in a preference list would otherwise change the
    matching without any warning.
    """
    for side, prefs, other in (
        ("proposer", proposer_prefs, receiver_prefs),
        ("receiver", receiver_prefs, proposer_prefs),
    ):
        if not isinstance(prefs, dict):
            raise MarketError(f"{side} preferences must be an object")
        for name, lst in prefs.items():
            if not isinstance(name, str):
                raise MarketError(f"{side} names must be strings")
            for other_name in _as_list(name, lst, side):
                if other_name not in other:
                    raise MarketError(
                        f"{side} {name!r} ranks unknown partner {other_name!r}"
                    )
    return (
        {name: list(lst) for name, lst in proposer_prefs.items()},
        {name: list(lst) for name, lst in receiver_prefs.items()},
    )


def _acceptable(proposer_prefs, receiver_prefs):
    """Drop pairs that either side refuses (absent from their list)."""
    recv_sets = {r: set(lst) for r, lst in receiver_prefs.items()}
    prop = {
        p: [r for r in lst if p in recv_sets.get(r, ())]
        for p, lst in proposer_prefs.items()
    }
    prop_sets = {p: set(lst) for p, lst in prop.items()}
    recv = {
        r: [p for p in lst if r in prop_sets.get(p, ())]
        for r, lst in receiver_prefs.items()
    }
    return prop, recv


def gale_shapley(proposer_prefs, receiver_prefs):
    """Return the proposer-optimal stable matching (one-to-one).

    ``proposer_prefs`` maps proposer -> ordered receiver list;
    ``receiver_prefs`` maps receiver -> ordered proposer list. Preference lists
    need not be complete and the two sides need not be the same size. The
    result maps every proposer to a receiver or ``None``.
    """
    proposer_prefs, receiver_prefs = validate_market(proposer_prefs, receiver_prefs)
    proposer_prefs, receiver_prefs = _acceptable(proposer_prefs, receiver_prefs)

    rank = {r: {p: i for i, p in enumerate(lst)} for r, lst in receiver_prefs.items()}
    nxt = {p: 0 for p in proposer_prefs}
    held = {}  # receiver -> proposer
    free = deque(proposer_prefs)

    while free:
        p = free.popleft()
        prefs = proposer_prefs[p]
        if nxt[p] >= len(prefs):
            continue  # exhausted every acceptable receiver: unmatched
        r = prefs[nxt[p]]
        nxt[p] += 1
        current = held.get(r)
        if current is None:
            held[r] = p
        elif rank[r][p] < rank[r][current]:
            held[r] = p
            free.append(current)
        else:
            free.append(p)

    pairs = {p: None for p in proposer_prefs}
    for r, p in held.items():
        pairs[p] = r
    return pairs


def blocking_pairs(assignment, proposer_prefs, receiver_prefs):
    """Return every blocking pair of a one-to-one assignment.

    A pair (p, r) blocks when both strictly prefer each other to their current
    partner, treating "unmatched" as worse than every acceptable partner.
    """
    proposer_prefs, receiver_prefs = validate_market(proposer_prefs, receiver_prefs)
    proposer_prefs, receiver_prefs = _acceptable(proposer_prefs, receiver_prefs)

    rank_p = {p: {r: i for i, r in enumerate(lst)} for p, lst in proposer_prefs.items()}
    rank_r = {r: {p: i for i, p in enumerate(lst)} for r, lst in receiver_prefs.items()}
    reverse = {r: p for p, r in assignment.items() if r is not None}

    found = []
    for p, current in assignment.items():
        limit = rank_p[p][current] if current is not None else len(proposer_prefs[p])
        for r in proposer_prefs[p][:limit]:
            other = reverse.get(r)
            if other is None:
                found.append((p, r))
            elif rank_r[r][p] < rank_r[r][other]:
                found.append((p, r))
    return found


def hospital_residents(resident_prefs, hospital_prefs, capacity):
    """Return the resident-optimal stable matching for capacities.

    ``capacity`` maps each hospital to a positive integer. The result maps every
    resident to a hospital or ``None``.
    """
    resident_prefs, hospital_prefs = validate_market(resident_prefs, hospital_prefs)
    resident_prefs, hospital_prefs = _acceptable(resident_prefs, hospital_prefs)

    cap = {}
    for name in hospital_prefs:
        value = capacity.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise MarketError(f"hospital {name!r} needs a positive integer capacity")
        cap[name] = value

    rank = {h: {p: i for i, p in enumerate(lst)} for h, lst in hospital_prefs.items()}
    nxt = {p: 0 for p in resident_prefs}
    held = {h: [] for h in hospital_prefs}  # hospital -> residents (best first)
    free = deque(resident_prefs)

    while free:
        p = free.popleft()
        prefs = resident_prefs[p]
        if nxt[p] >= len(prefs):
            continue
        h = prefs[nxt[p]]
        nxt[p] += 1
        seats = held[h]
        if len(seats) < cap[h]:
            seats.append(p)
            seats.sort(key=lambda who: rank[h][who])
        elif rank[h][p] < rank[h][seats[-1]]:
            loser = seats.pop()
            seats.append(p)
            seats.sort(key=lambda who: rank[h][who])
            free.append(loser)
        else:
            free.append(p)

    pairs = {p: None for p in resident_prefs}
    for h, seats in held.items():
        for p in seats:
            pairs[p] = h
    return pairs


def blocking_pairs_capacity(assignment, resident_prefs, hospital_prefs, capacity):
    """Return every blocking pair of a many-to-one assignment."""
    resident_prefs, hospital_prefs = validate_market(resident_prefs, hospital_prefs)
    resident_prefs, hospital_prefs = _acceptable(resident_prefs, hospital_prefs)
    rank_r = {p: {h: i for i, h in enumerate(lst)} for p, lst in resident_prefs.items()}
    rank_h = {h: {p: i for i, p in enumerate(lst)} for h, lst in hospital_prefs.items()}
    seats = {h: [] for h in hospital_prefs}
    for p, h in assignment.items():
        if h is not None:
            seats[h].append(p)

    found = []
    for p, current in assignment.items():
        limit = rank_r[p][current] if current is not None else len(resident_prefs[p])
        for h in resident_prefs[p][:limit]:
            holders = seats[h]
            if len(holders) < capacity.get(h, 0):
                found.append((p, h))
            elif rank_h[h][p] < max(rank_h[h][q] for q in holders):
                found.append((p, h))
    return found


def random_market(n_proposers, n_receivers, seed=None, completeness=1.0):
    """Build a random market; ``completeness`` < 1 drops unacceptable pairs."""
    rng = random.Random(seed)
    proposers = [f"p{i}" for i in range(n_proposers)]
    receivers = [f"r{i}" for i in range(n_receivers)]
    prop = {}
    for p in proposers:
        lst = list(receivers)
        rng.shuffle(lst)
        keep = max(1, round(len(lst) * completeness)) if lst else 0
        prop[p] = lst[:keep]
    recv = {}
    for r in receivers:
        lst = list(proposers)
        rng.shuffle(lst)
        keep = max(1, round(len(lst) * completeness)) if lst else 0
        recv[r] = lst[:keep]
    return prop, recv


def render(assignment, title):
    """Format an assignment as a plain text table."""
    width = max([len(name) for name in assignment] + [len("proposer")])
    lines = [title, ""]
    lines.append(f"{'proposer'.ljust(width)}  {'receiver'}")
    lines.append(f"{'-' * width}  {'-' * 8}")
    for name, target in assignment.items():
        lines.append(f"{name.ljust(width)}  {target if target is not None else '(unmatched)'}")
    return "\n".join(line.rstrip(" ") for line in lines) + "\n"


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise MarketError(f"cannot read {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise MarketError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="stable_matching",
        description="Compute a stable matching with Gale-Shapley.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("market", nargs="?", help="JSON market file")
    source.add_argument("--random", type=int, metavar="N", help="generate a random NxN market")
    parser.add_argument("--seed", type=int, default=None, help="seed for --random")
    parser.add_argument("--capacity", type=int, default=1, help="seats per receiver with --random")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)

    try:
        if args.random is not None:
            if args.random < 0:
                raise MarketError("--random needs a non-negative size")
            prop, recv = random_market(args.random, args.random, args.seed)
            capacity = {r: args.capacity for r in recv}
        else:
            data = _load(args.market)
            if not isinstance(data, dict) or "proposers" not in data or "receivers" not in data:
                raise MarketError("market JSON needs 'proposers' and 'receivers' objects")
            prop, recv = data["proposers"], data["receivers"]
            capacity = data.get("capacity") or {r: 1 for r in recv}

        many = any(capacity[r] > 1 for r in capacity if r in recv)
        if many:
            assignment = hospital_residents(prop, recv, capacity)
            blocking = blocking_pairs_capacity(assignment, prop, recv, capacity)
        else:
            assignment = gale_shapley(prop, recv)
            blocking = blocking_pairs(assignment, prop, recv)
    except MarketError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if args.json:
        payload = {
            "matching": {p: r for p, r in assignment.items()},
            "stable": not blocking,
            "blocking_pairs": [list(pair) for pair in blocking],
        }
        sys.stdout.buffer.write(
            (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        )
        return 0 if not blocking else 1

    matched = sum(1 for r in assignment.values() if r is not None)
    text = render(assignment, f"matched {matched} of {len(assignment)} proposers")
    text += f"\nstable: {'yes' if not blocking else 'no'}\n"
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0 if not blocking else 1


if __name__ == "__main__":
    sys.exit(main())
