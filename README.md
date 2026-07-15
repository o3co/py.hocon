# py.hocon

Full [Lightbend HOCON specification](https://github.com/lightbend/config/blob/main/HOCON.md)-compliant
parser for Python.

Sibling of [go.hocon](https://github.com/o3co/go.hocon),
[ts.hocon](https://github.com/o3co/ts.hocon), and
[rs.hocon](https://github.com/o3co/rs.hocon) — the same 3-stage pipeline
(Lexer → Parser → Resolver), verified against the same conformance corpus
([xx.hocon](https://github.com/o3co/xx.hocon): 134 shared fixtures with
Lightbend-generated expected output, plus a 209-item spec checklist).

**Conformance: 134/134 spec corpus, 14/16 Lightbend suite** — at parity with
go.hocon and rs.hocon. (The 2 held-out fixtures reference JVM system properties
`${?java.version}` / `${?user.home}`; every non-JVM parser caps at 14/16.)

```python
import hocon

config = hocon.parse_file("application.conf")
config.get_string("app.name")
config.get_duration("app.timeout")
```

- Zero runtime dependencies (pure stdlib)
- Python 3.11+
- Fully typed (`py.typed`)

## Development

```bash
make setup      # create .venv and install dev dependencies (needs python3.11+)
make check      # ruff + mypy + pytest
make testdata   # sync the conformance corpus from o3co/xx.hocon
```

Spec-compliance tracking lives in [docs/spec-compliance.md](docs/spec-compliance.md).

## License

Apache-2.0
