# py.hocon

[Lightbend HOCON 仕様](https://github.com/lightbend/config/blob/main/HOCON.md)完全準拠を目指す
Python 用 HOCON パーサー。

[go.hocon](https://github.com/o3co/go.hocon) /
[ts.hocon](https://github.com/o3co/ts.hocon) /
[rs.hocon](https://github.com/o3co/rs.hocon) の sibling 実装。同一の 3-stage pipeline
(Lexer → Parser → Resolver) で実装し、共有 conformance コーパス
([xx.hocon](https://github.com/o3co/xx.hocon): 134 fixtures + 209 項目 spec checklist)
で検証する。

**Conformance: spec corpus 134/134、Lightbend suite 14/16** — go.hocon / rs.hocon
と同値。(held-out 2 件は JVM system property `${?java.version}` / `${?user.home}`
参照で、非 JVM パーサーは 14/16 が上限。)

- 外部 runtime 依存ゼロ (pure stdlib)
- Python 3.11+
- 型付き (`py.typed`)

## 開発

```bash
make setup      # .venv 作成 + dev 依存インストール (python3.11+ が必要)
make check      # ruff + mypy + pytest
make testdata   # o3co/xx.hocon から conformance コーパスを同期
```

## License

Apache-2.0
