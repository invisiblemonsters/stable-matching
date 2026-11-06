# stable-matching

Gale-Shapley deferred acceptance in a single dependency-free Python file: one-to-one stable marriage and the many-to-one hospital/residents variant.

A matching is **stable** when no unmatched pair would both rather be with each other than with their current assignment. The algorithm always finds one, and the one it finds is optimal for the side that proposes.

## Usage

```
python stable_matching.py market.json
```

`market.json` describes both sides:

```json
{
  "proposers": {
    "alice": ["x", "y", "z"],
    "bob":   ["y", "x", "z"],
    "carol": ["x", "y", "z"]
  },
  "receivers": {
    "x": ["bob", "alice", "carol"],
    "y": ["alice", "bob", "carol"],
    "z": ["alice", "bob", "carol"]
  }
}
```

```
$ python stable_matching.py example.json
matched 3 of 3 proposers

proposer  receiver
--------  --------
alice     x
bob       y
carol     z

stable: yes
```

Preference lists do not have to be complete or the same length; leaving a name off a list means "will not accept". Anyone who runs out of acceptable partners is reported as `(unmatched)`.

### Capacities (hospital/residents)

Add a `capacity` object and each receiver accepts up to that many:

```json
{
  "proposers": {"a": ["h1", "h2"], "b": ["h1", "h2"], "c": ["h1", "h2"]},
  "receivers": {"h1": ["a", "b", "c"], "h2": ["a", "b", "c"]},
  "capacity": {"h1": 2, "h2": 1}
}
```

```
$ python stable_matching.py hospitals.json
matched 3 of 3 proposers
...
```

### Options

```
--random N        generate a random N x N market instead of reading a file
--seed S          seed for --random (same seed, same market)
--capacity K      seats per receiver when using --random (default 1)
--json            emit {"matching": ..., "stable": ..., "blocking_pairs": [...]}
```

Exit status is `0` for a stable result, `1` if a blocking pair was somehow found, and `2` for a malformed market file.

## API

```python
from stable_matching import gale_shapley, hospital_residents, blocking_pairs

pairs = gale_shapley(proposer_prefs, receiver_prefs)   # {"alice": "x", "bob": None, ...}
pairs = hospital_residents(resident_prefs, hospital_prefs, {"h1": 2, "h2": 1})
blocking_pairs(pairs, proposer_prefs, receiver_prefs)  # [] when stable
```

## Tests

```
python -m unittest test_stable_matching.py -v
```

19 tests. Besides known instances and malformed-input cases, the suite checks the solver against a brute-force reference: every partial matching of small random markets is enumerated, the library's result is verified stable by a separately written checker, and its pairing is compared with the best stable matching for every proposer. The hospital variant is checked for capacity limits, stability, and resident-optimality over random markets. CLI tests capture raw bytes to confirm UTF-8 output and no CRLF rewriting.

## Notes

The implementation filters out pairs that either side declines before proposing, so incomplete lists cannot create "forced" matches. Deferred acceptance runs in O(n·m) proposals in the worst case.

MIT licensed.
