"""Micro-benchmarks for py.hocon. Run: `make bench` (or `python benchmarks/bench.py`).

Each scenario times parse + a `get_string` lookup, mirroring the scenario set the
sibling implementations (ts.hocon / rs.hocon) publish so the numbers are roughly
comparable across languages. Timings are indicative, not a rigorous benchmark.
"""

from __future__ import annotations

import time

import hocon


def _small() -> str:
    return "\n".join(f'key{i} = "value{i}"' for i in range(10))


def _medium() -> str:
    return "\n".join(f'key{i} = "value{i}"' for i in range(100))


def _large() -> str:
    return "\n".join(f'key{i} = "value{i}"' for i in range(1000))


def _substitutions(n: int) -> str:
    lines = ['base = "x"']
    lines += [f"key{i} = ${{base}}{i}" for i in range(n)]
    return "\n".join(lines)


def _nested(depth: int) -> str:
    open_ = "".join(f"level{i} {{ " for i in range(depth))
    close = "}" * depth
    return f'{open_}leaf = "v" {close}'


def _leaf_path(depth: int) -> str:
    return ".".join(f"level{i}" for i in range(depth)) + ".leaf"


def bench(name: str, text: str, path: str, iters: int) -> None:
    # warmup
    for _ in range(max(1, iters // 10)):
        hocon.parse(text).get_string(path)
    start = time.perf_counter()
    for _ in range(iters):
        hocon.parse(text).get_string(path)
    elapsed = time.perf_counter() - start
    per_op = elapsed / iters
    ops = 1.0 / per_op
    print(f"{name:28s} {ops:>12,.0f} ops/s  {per_op * 1e6:>8.1f} us/op")


def main() -> None:
    bench("Small config (10 keys)", _small(), "key0", 20000)
    bench("Medium config (100 keys)", _medium(), "key0", 5000)
    bench("Large config (1000 keys)", _large(), "key0", 500)
    bench("10 substitutions", _substitutions(10), "key0", 10000)
    bench("50 substitutions", _substitutions(50), "key0", 4000)
    bench("100 substitutions", _substitutions(100), "key0", 2000)
    bench("Depth 5 nesting", _nested(5), _leaf_path(5), 20000)
    bench("Depth 10 nesting", _nested(10), _leaf_path(10), 20000)
    bench("Depth 20 nesting", _nested(20), _leaf_path(20), 10000)


if __name__ == "__main__":
    main()
