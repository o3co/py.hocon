# py.hocon — Python 向け HOCON パーサー

[![PyPI](https://img.shields.io/pypi/v/hocon-parser.svg)](https://pypi.org/project/hocon-parser/)
[![Python](https://img.shields.io/pypi/pyversions/hocon-parser.svg)](https://pypi.org/project/hocon-parser/)
[![CI](https://github.com/o3co/py.hocon/actions/workflows/test.yml/badge.svg)](https://github.com/o3co/py.hocon/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/o3co/py.hocon/branch/main/graph/badge.svg)](https://codecov.io/gh/o3co/py.hocon)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Spec conformance](https://img.shields.io/badge/spec%20corpus-134%2F134-brightgreen.svg)](docs/spec-compliance.md)

[Lightbend HOCON 仕様](https://github.com/lightbend/config/blob/main/HOCON.md)準拠の
Python パーサー。手書きの字句解析器・再帰下降パーサー・型付き `Config` API を備え、
外部 runtime 依存ゼロ (pure stdlib)、Python 3.11+、型付き (`py.typed`)。現在の準拠率は
[仕様準拠](#仕様準拠) を参照。

> **[Claude](https://claude.ai/)（Anthropic）による実装** — Claude Code を用いて
> 設計・実装され、sibling の [ts.hocon](https://github.com/o3co/ts.hocon) から移植されました。

[English](README.md)

> **ライブラリの立場** — py.hocon は HOCON 設定ローダーです。`.conf` 設定ファイルを
> 読み込み、`Config` API (`get_string` / `get_number` / `get_boolean` /
> `get_duration` / `get_bytes` / `get_period` / `to_object`) 経由で型付き
> アクセスを提供します。
> 低レベルなパーサー API ではなく、`hocon._internal` 配下の内部型は minor version 間で
> 変更されることがあります。
>
> **クロス言語準拠** — 本実装は [o3co/xx.hocon](https://github.com/o3co/xx.hocon) の
> 共有 expected-JSON フィクスチャに対して、[ts.hocon](https://github.com/o3co/ts.hocon) /
> [go.hocon](https://github.com/o3co/go.hocon) / [rs.hocon](https://github.com/o3co/rs.hocon)
> と共にテストされ、4 実装すべてが同一の Lightbend HOCON 仕様を満たすことを保証します。

---

## クイックスタート

### 1. インストール

```sh
pip install hocon-parser
```

import 名は `hocon` です:

```python
import hocon
```

### 2. 使い方

```python
import hocon

cfg = hocon.parse("""
    server {
        host = "localhost"
        port = 8080
    }
    database {
        url = "jdbc:postgresql://localhost/mydb"
        pool-size = 10
    }
""")

cfg.get_string("server.host")   # "localhost"
cfg.get_int("server.port")      # 8080
cfg.has("server.host")          # True

# Config は Mapping — dict スタイルのアクセスがそのまま使える
cfg["server.host"]              # "localhost"
cfg["database"]                 # {"url": ..., "pool-size": 10}
cfg.get("server.timeout", 30)   # 30 (不在パスの default)
"server.port" in cfg            # True
dict(cfg)                       # config 全体の素の nested dict
```

自分の型へ直接 decode することもできます:

```python
from dataclasses import dataclass

@dataclass
class Database:
    url: str
    pool_size: int   # ← `pool-size` にマッチ

db = cfg.decode(Database, path="database")
db.pool_size                    # 10、静的に型が付く
```

## なぜ HOCON？

| | `.env` | JSON | YAML | HOCON |
|---|---|---|---|---|
| コメント | No | No | Yes | Yes |
| ネスト | No | Yes | Yes | Yes |
| 参照 / 置換 | No | No | No | Yes (`${var}`) |
| ファイル取り込み | No | No | No | Yes (`include`) |
| オブジェクトマージ | No | No | Anchors (脆弱) | Yes (deep merge) |
| オプショナル値 | No | No | No | Yes (`${?var}`) |
| 末尾カンマ | N/A | No | N/A | Yes |
| 非クォート文字列 | Yes | No | Yes | Yes |

HOCON は単なるシリアライズ形式ではなく **設定注入言語** です。JSON・YAML・TOML は
データ構造を記述し、ファイルの重ね合わせ・環境変数・参照解決をアプリ側 (Pydantic /
attrs 等) に委ねます。HOCON はそれらを仕様に組み込んでおり、プログラムが設定を読む
時点で fallback ファイルはマージ済み、`${VAR}` 参照は単一の合成オブジェクトへ解決済み
です。「この層にこの値はあるか？」という条件分岐が形式の境界で消えます。

加えて HOCON は YAML の可読性と JSON の構造を兼ね備え、フラットな key-value を超える
設定に適します。

## 機能

- 完全な HOCON パース: オブジェクト・配列・スカラー・置換 (`${path}` / `${?path}`)
- 自己参照置換 (`path = ${path}:/extra`)、循環検出付き
- 重複キーの deep-merge (後勝ち)
- `+=` 追記演算子
- `include`: `include "file.conf"` / `include file("...")` /
  `include package("id", "file")` / `include required(...)`
- トリプルクォート文字列 (`"""..."""`)
- Duration / period / byte-size パース (`get_duration()` / `get_period()` /
  `get_bytes()`)
- 環境変数置換 (`${HOME}`) と env-var list 展開 (`${NAME[]}` → `NAME_0`, `NAME_1`, …)
- 数値キーオブジェクト → 配列変換
- `.properties` include
- 遅延解決ライフサイクル: `parse(..., resolve_substitutions=False)` →
  `with_fallback` → `resolve()`
- `Config` は `collections.abc.Mapping`: `cfg[path]`、`path in cfg`、
  `cfg.get(path, default)`、イテレーション、`len`、`dict(cfg)`、`**cfg`
- 型付き decode: `cfg.decode(MyDataclass)` — dataclass の再帰構築
  (kebab-case / camelCase のキーマッチ、default、`Optional`、`list[T]` /
  `dict[str, T]`、`timedelta` duration、`Enum`) と Pydantic v2 への
  `model_validate` 委譲
- 外部 runtime 依存ゼロ (pure stdlib)、型付き (`py.typed`)

## API リファレンス

### パース関数

```python
import hocon

hocon.parse(text, *, base_dir=None, env=None, read_file=None,
            resolve_substitutions=True, origin_description=None,
            resolve_from=None, package_resolver=None) -> hocon.Config
hocon.parse_string(text, **opts)   # parse() のエイリアス
hocon.parse_file(path, **opts)     # include はファイルのディレクトリ基準で解決
```

パースオプション (キーワード専用):

| Option | Type | 説明 |
|--------|------|-------------|
| `base_dir` | `str` | `include` 解決の基準ディレクトリ |
| `env` | `dict[str, str]` | 置換用の環境変数 (既定: `os.environ`) |
| `read_file` | `(str) -> str` | カスタムファイルリーダー |
| `resolve_substitutions` | `bool` | パース時に置換を解決 (既定 `True`)。`False` で遅延 `Config` を返す |
| `origin_description` | `str` | エラーメッセージに出す source 名 |
| `resolve_from` / `package_resolver` | — | `include package(...)` の解決を制御 |

### Config メソッド

型付き getter は失敗時に例外を送出します。パスはドット記法で、ドットを含むキーは
クォートセグメントを使います (`config.get_string('"a.b".c')`)。

| メソッド | 返り値 | 例外条件 |
|--------|---------|-----------|
| `get(path, default=None)` | 値 または `default` | — |
| `config[path]` | 値 | 不在なら `KeyError` |
| `get_string(path)` | `str` | 不在・型不一致・未解決 |
| `get_number(path)` | `int \| float` | 不在・非数値・未解決 |
| `get_int(path)` | `int` | 不在・非数値・未解決 |
| `get_float(path)` | `float` | 不在・非数値・未解決 |
| `get_boolean(path)` | `bool` | 不在・型不一致・未解決 |
| `get_duration(path, unit=None)` | `float` | 不在・型不一致・不正な duration |
| `get_bytes(path, unit=None)` | `float` | 不在・型不一致・不正な byte size |
| `get_period(path)` | `Period` | 不在・型不一致・不正な period |
| `get_config(path)` | `Config` | 不在・オブジェクトでない・未解決 |
| `get_list(path)` | `list` | 不在・配列でない・未解決 |
| `get_value(path)` | `HoconValue \| None` | サブツリー未解決 |
| `decode(cls, path=None)` | `cls` のインスタンス | パス/フィールド欠落・型不一致・未解決 |
| `has(path)` | `bool` | — |
| `keys()` | `list[str]` | — |
| `with_fallback(fallback)` | `Config` | — |
| `resolve(*, allow_unresolved=False, use_system_environment=True)` | `Config` | 解決不能な置換 (`allow_unresolved` 時を除く) |
| `resolve_with(source, *, ...)` | `Config` | source 未解決、または解決不能な置換 |
| `is_resolved()` | `bool` | — |
| `to_object()` | `dict / list / scalar` | — |

`get_boolean` は `yes`/`no`・`on`/`off` も受け付けます。`get_number` は整数字句なら
`int`、それ以外は `float` を返します。

`Config` はトップレベルキーに対する `collections.abc.Mapping` を実装します:
イテレーション、`len(cfg)`、`dict(cfg)`、`**cfg`、`items()` / `values()` が使えます。
`cfg[path]` と `path in cfg` はドット記法のパス式も受け付けます
(`cfg["server.host"]`)。ドットを含むリテラルなトップレベルキーはパス走査より
優先されるため、イテレーションが返すキーは必ずそのまま index できます。
Mapping の意味論は `dict` に従います: 等価性は値ベース (`Config` は同内容の
`dict` と等しい)、空 config は falsy、`Config` は unhashable。明示的な HOCON
`null` は「存在する値」です — `cfg.get(path, default)` は `None` を返し、
`path in cfg` は `True` になります。

### 型付き decode

`cfg.decode(cls, path=None)` は config 全体 (または `path` の値) から `cls` の
インスタンスを構築します。go.hocon の `Unmarshal` / `UnmarshalPath` と同じ契約です:

- **dataclass** は型ヒントから再帰的に構築します。`field(metadata={"hocon":
  key})` alias がある場合はそのキー**のみ**を照合します (go の struct tag /
  serde の `rename` と同じで、フィールド名への fallback はしない)。alias が
  ない場合は 完全一致 → kebab-case (`pool_size` → `pool-size`) → camelCase
  (`poolSize`) の順で照合し、最初の一致を使います。`metadata={"hocon": "-"}`
  はフィールドを skip します (default が必須)。
  キーが不在のフィールドは dataclass の default を使い、default がなければ
  エラー。config 側の余分なキーは無視します。
- **Pydantic v2 モデル** (`model_validate` を持つ任意のクラス — pydantic を
  import はしない) には decode 済みの素のオブジェクトを丸ごと渡し、検証は
  モデル側に任せます。
- **対応ヒント**: ネストした dataclass、`list[T]` (S15 数値キーオブジェクト
  含む)、`dict[str, T]`、`Optional[T]` / `T | None`、`Any`、
  `str` / `bool` / `int` / `float`、`Enum` (値 → 名前の順)、
  `datetime.timedelta` (HOCON duration、例 `"10s"`)、`Period`、`Config`
  (サブツリーを動的なまま保持)。`cls` 自体も任意の対応式でよく、
  `cfg.decode(list[Server], path="servers")` のように使えます。
- **coercion** は型付き getter に従います: `bool` は `yes`/`on` を受理、
  `str` は非 null スカラーの raw テキストを受理、`int` は整数値の float を
  受理し、整数性は 10 進テキストから判定します (`3.0` → `3`、`2.5` → エラー)。
  HOCON `null` は optional なフィールドにしか decode されません。

### 値ファクトリ

```python
from hocon import from_map, empty

cfg = from_map({"server": {"host": "localhost", "port": 8080}})
cfg.get_int("server.port")   # 8080

empty()                      # キーなしの解決済み Config
```

`from_map` のキーはパス式ではなく **プレーンキー** として扱われます —
`{"a.b": 1}` は `a.b` という名前のトップレベルキーになります。

### 構造アクセス

デコード済みの `to_object()` / `get()` に加え、`get_value()` は生の値ツリーを公開し、
スタンドアロンのアクセサで内省できます:

```python
from hocon import as_string, as_object, is_scalar, is_null

node = cfg.get_value("server")      # HoconValue
as_object(node)                     # dict[str, HoconValue] | None
is_scalar(cfg.get_value("server.port"))   # True
```

### 遅延解決

ランタイム設定注入のため、パース・fallback 重ね・解決を分離できます:

```python
import hocon
from hocon import from_map

# 1. 解決せずにパース — 置換は遅延
cfg = hocon.parse(
    'version = ${shortversion}-${CI_RUN_NUMBER}\n'
    'variables { shortversion = "1.2.3" }',
    resolve_substitutions=False,
)
cfg.is_resolved()   # False — ${CI_RUN_NUMBER} が未解決

# 2. ランタイム fallback を重ねる
runtime = from_map({"CI_RUN_NUMBER": "42"})
variables = cfg.get_config("variables")
merged = cfg.with_fallback(runtime).with_fallback(variables)

# 3. fallback スタック全体を解決
resolved = merged.resolve(use_system_environment=False)
resolved.get_string("version")   # "1.2.3-42"
```

`resolve_with` は source のキーを結果にマージせず、source を lookup として receiver を
解決します:

```python
receiver = hocon.parse("r = ${key}", resolve_substitutions=False)
source = from_map({"key": "val"})
result = receiver.resolve_with(source)
result.has("key")        # False — source のキーは含まれない
result.get_string("r")   # "val"
```

## エラー型

```python
from hocon import (
    ParseError,          # 字句/構文エラー: .line, .col, .file
    ResolveError,        # 置換/include エラー: .path, .line, .col, .file
    PackageLookupError,  # include package(...) 未発見 (ResolveError のサブクラス)
    ConfigError,         # 型不一致・パス不在: .path
    NotResolvedError,    # 未解決パスへの getter (ConfigError のサブクラス)
)
```

## HOCON の例

```hocon
# コメントは # または //
database {
  host = "db.example.com"
  port = 5432
  url  = "jdbc:"${database.host}":"${database.port}
}

# 重複キーは deep-merge (スカラーは後勝ち)
server { host = localhost }
server { port = 8080 }      // 結果: { host: "localhost", port: 8080 }

# 自己参照追記
path = "/usr/bin"
path = ${path}":/usr/local/bin"

# += 省略記法
items = [1]
items += 2
items += 3   // [1, 2, 3]

# include
include "defaults.conf"
include file("overrides.conf")

# トリプルクォート複数行文字列
description = """
  This is a
  multiline string.
"""
```

### Duration / Period / Byte サイズ

```python
from hocon import Period

c = hocon.parse("""
    timeout   = "30s"
    cache-ttl = "5m"
    retention = "2w"
    max-size  = "512MiB"
""")

c.get_duration("timeout")         # 30000.0 (ms)
c.get_duration("timeout", "s")    # 30.0
c.get_period("retention")         # Period(years=0, months=0, days=14)
c.get_bytes("max-size")           # 536870912 (bytes)
c.get_bytes("max-size", "MiB")    # 512.0
```

Duration 単位: `ns` / `us` / `ms` / `s` / `m` / `h` / `d` (および `seconds` 等の
長形式)。単位名は **大文字小文字を区別** し小文字のみ (HOCON 仕様 S19.8)。Byte 単位は
より寛容で、正準形 + 小文字エイリアス (`kb` 等) + 任意ケースの長形式 (`megabytes`) +
1 文字の 2 の冪 (`K`/`k`、Lightbend 準拠、S21.4) を受け付けます。

`get_period` (仕様 S20.1–S20.4) は `Period(years, months, days)` (frozen
dataclass、rs.hocon の `Period` struct 準拠) を返します。単位: `d`/`day`/`days`
(単位なしの数値の default)、`w`/`week`/`weeks` (days に換算)、
`m`/`mo`/`month`/`months`、`y`/`year`/`years` — duration と同じく小文字のみ。
Period は **整数のみ** (Lightbend `Integer.parseInt`) で、`"7.5"` のような小数は
`ConfigError` になります (`get_duration` / `get_bytes` は小数可)。負の period は
許容されます。

## パフォーマンス

`benchmarks/bench.py` による目安値 (各反復でパース + `get_string` lookup)。
`make bench` で自環境で再現できます。

| シナリオ | ops/sec | 1 回あたり |
|---|---|---|
| 小 (10 keys) | ~5,700 | ~175 µs |
| 中 (100 keys) | ~600 | ~1.7 ms |
| 大 (1,000 keys) | ~57 | ~17.7 ms |
| 置換 10 | ~3,700 | ~270 µs |
| 置換 100 | ~400 | ~2.5 ms |
| ネスト深さ 20 | ~2,000 | ~500 µs |

pure-Python のため、コンパイル / V8 系の sibling (go / rs / ts) より概ね 30〜40 倍
遅くなります。起動時に一度読むだけの通常の設定なら無視できるコストで、1,000 key でも
20 ms 未満でパースできます。ホットパスで巨大な設定を扱う場合は `Config` をキャッシュ
してください。

## 仕様準拠

[Lightbend HOCON 仕様](https://github.com/lightbend/config/blob/main/HOCON.md)への
準拠は [`docs/spec-compliance.md`](docs/spec-compliance.md) に項目単位で記録。
横断値は [`xx.hocon/docs/compliance-matrix.md`](https://github.com/o3co/xx.hocon/blob/main/docs/compliance-matrix.md)
を参照。

| コーパス | py.hocon | go.hocon / rs.hocon (参照) |
|---|---:|---:|
| Spec corpus (134) | **134 (100.0%)** | 134 (100.0%) |
| Lightbend suite (16) | **14/16** | 14/16 |

参照 sibling 実装と同値。held-out の Lightbend 2 件は JVM system property
(`${?java.version}` / `${?user.home}`) 参照で、非 JVM パーサーは 14/16 が上限です。

## 関連プロジェクト

| プロジェクト | 言語 | レジストリ | 説明 |
|---------|----------|----------|-------------|
| [ts.hocon](https://github.com/o3co/ts.hocon) | TypeScript | [npm](https://www.npmjs.com/package/@o3co/ts.hocon) | TypeScript/Node.js 向け HOCON パーサー |
| [go.hocon](https://github.com/o3co/go.hocon) | Go | [pkg.go.dev](https://pkg.go.dev/github.com/o3co/go.hocon) | Go 向け HOCON パーサー |
| [rs.hocon](https://github.com/o3co/rs.hocon) | Rust | [crates.io](https://crates.io/crates/hocon-parser) | Rust 向け HOCON パーサー |
| [hocon2](https://github.com/o3co/hocon2) | Go | [pkg.go.dev](https://pkg.go.dev/github.com/o3co/hocon2) | HOCON → JSON/YAML/TOML/Properties CLI |

## ベストプラクティス

### 設定の構造

- **ドメインで分割する**: 論理単位ごとにファイルを分ける (`database.conf`,
  `server.conf`, `logging.conf`)
- **合成には `include` を使う**: ドメイン別ファイルを組み合わせて全体を構成する
- **設定にロジックを持ち込まない**: HOCON は宣言的なデータのためのもので、条件分岐や
  計算のためのものではありません

### 環境変数

- **`${ENV}` は最小限に**: `${?ENV}` (optional) と設定側の妥当な default を優先する
- **ローカル開発で環境変数を必須にしない**: 何も設定しなくても default で動くようにする
- **必要な環境変数を文書化する**: プロジェクトの README か `.env.example` に列挙する
- **名前空間ごとマウントする場合**: `hocon.adapters.env` が prefix 配下をまとめて
  サブツリーにします (`APP_DB__HOST` → `db.host`)。階層の区切りは `__` **のみ**です —
  [フォーマットアダプタ](#フォーマットアダプタ)を参照

### dev / prod の分離

```text
config/
├── application.conf    # 共通の default
├── dev.conf            # include "application.conf" + dev 用の上書き
└── prod.conf           # include "application.conf" + prod 用の上書き
```

### バリデーション

設定の検証は利用箇所ではなく起動時に行います。型付きの構造 (dataclass / `attrs` /
Pydantic) に読み込むと、エラーが早期に表面化します:

```python
from dataclasses import dataclass
import hocon

@dataclass
class ServerConfig:
    host: str
    port: int

cfg = hocon.parse_file("application.conf")
server = cfg.decode(ServerConfig, path="server")
# フィールド欠落や型不一致は起動時に fail する
```

## フォーマットアダプタ

**他のプログラム**が所有する設定ファイルを HOCON としてマウントでき、自分の
ドキュメントの `${...}` からその中身を参照できます:

```python
import hocon
from hocon.adapters import env

base = env.load(prefix="APP_")               # APP_DB__HOST -> db.host
cfg = hocon.parse(src, resolve_substitutions=False)
merged = cfg.with_fallback(base).resolve()
```

解決を遅らせるのが重要です: 素の `parse` はパースしながら解決するため、fallback を
付ける前に `${...}` の解決が失敗してしまいます。

| モジュール | 追加インストール | 備考 |
| --- | --- | --- |
| `hocon.adapters.properties` | — | `java.util.Properties`。`include` と構文層を共有 |
| `hocon.adapters.env` | — | prefix 付き名前空間をまとめてマウント。`.env` も読める |
| `hocon.adapters.jsonc` | — | コメントと trailing comma 付き JSON |
| `hocon.adapters.json5` | — | JSON5 1.0.0、手書き scanner |
| `hocon.adapters.toml` | — | Python 3.11 同梱の `tomllib` 経由 |
| `hocon.adapters.yaml` | `pip install hocon-parser[yaml]` | `ruamel.yaml` 経由 |

依存が要るのは YAML だけで、base install は pure stdlib のままです。プレーンな JSON に
アダプタは不要です — HOCON は JSON の上位集合なので `hocon.parse` がそのまま受け付け
ます。

外部のデータはデータのままです: マウントした値の中の `${a.b}` は参照ではなくただの
文字列になります。そのファイルは HOCON の構文に同意していないプログラムのものだから
です。

### 間違えやすいマッピング規則

**env — 階層の区切りは `__` のみ。** 変数名の中の `.` は階層ではなくキーの文字なので、
2 つの綴りは別のパスになります:

```python
cfg = env.load("APP_", {"APP_FOO__BAR": "nested", "APP_FOO.BAR": "literal"})
cfg.get_string("foo.bar")      # "nested"  — APP_FOO__BAR 由来
cfg.get_string('"foo.bar"')    # "literal" — APP_FOO.BAR 由来、クォートした 1 キー
```

別のパスである以上、衝突もしません。本当の衝突 (小文字化して同じパスになる
`APP_A__B` と `APP_a__b`) はエラーです — 環境変数の列挙順に優劣を決める根拠がない
ためです。`.env` ファイルは行の順序が確定しているので、そちらは後勝ちになります。
セグメントの小文字化は **ASCII のみ** (`A`–`Z` だけで、それ以外の符号位置はそのまま)
です — 各言語の Unicode 規則を継承すると実装間でマッピングがずれるためです。単一の
`_` はセグメントの一部として残ります (`APP_DB__MAX_CONN` → `db.max_conn`)。

**env — UTF-8 として不正なエントリは値にならない。** Python は環境変数を
`surrogateescape` でデコードするため、デコードできないバイトは lone surrogate として
残り、後段で encode したときに初めて例外になります。扱いは「その変数を要求したか」で
決まります: `${VAR}` / `${?VAR}` は **存在しないもの**として扱い (optional は default に
フォールバック、必須形は通常の未解決エラー)、`env.load(prefix=...)` は mount した prefix
の内側にそのエントリがあれば **エラー**にします — 黙って落とすと、設定が欠けたまま
subtree だけが完全に見えてしまうためです。prefix の外側は検査しないので、無関係な
変数がデコード不能でも mount は壊れません。

**jsonc — コメントはトークンを分割する。** コメントは空白に置き換えて除去されるため、
`{"a": 1/*x*/2}` は `{"a": 12}` ではなく構文エラーになります。`//` コメントは LF
だけでなく CR でも終わります (VS Code が読む方言に合わせています)。

**json5 — 方言の所有者は reference implementation。** 文法は `json5` npm パッケージが
読む JSON5 1.0.0 です。そのため U+2028/U+2029 は `//` コメントを**終端します**
(jsonc とは意図的に異なります — あちらの所有者はコメントを素通しします)。マッピング
仕様の方が厳しい箇所は仕様が勝ちます: `Infinity`/`NaN` はどの綴りでもエラー、16 進・
10 進の整数は int64 に収まる必要があり、対にならない `\uXXXX` サロゲートはエラー、
重複キーは HOCON 流 (オブジェクト同士は merge、それ以外は後勝ち) です。

**properties — すべてのキーが普通のキー。** `__proto__` / `constructor` /
`prototype` も他のキーと同じく値ごと保持されます。Python の `dict` に汚染される
prototype は存在しないので、除外は行いません。

**全フォーマット共通 — 整数は int64、BOM はキーの一部ではない。** 取り込んだ整数が
`[-2^63, 2^63-1]` の範囲外ならエラーです (他実装が保持できない値を受け入れないため)。
先頭の UTF-8 BOM は各 `parse_file` が除去するので、最初のキーに紛れ込みません。

YAML のスカラー解決はライブラリの責務で、本パッケージの保証ではありません。
`ruamel.yaml` は YAML 1.2 を読むので `no` は文字列 `"no"` のままです。PyYAML は
YAML 1.1 で `False` に解決してしまう (Norway problem) ため default にしていません。
別のライブラリを使いたい場合は、呼び出し側でデコードしたツリーを渡します:

```python
import yaml as pyyaml
from hocon.adapters.yaml import from_value

cfg = from_value(pyyaml.safe_load(src), "their-file.yml")
```

## 既知の制限

- **`include url(...)`** 非対応。リモート設定の取得はパーサーの範囲外です。HTTP
  クライアントで取得して `parse()` に渡してください。
- **`include classpath(...)`** 非対応。JVM 固有の include 形式です。
- **`include package(...)`** は Python パッケージマネージャ探索ではなく filesystem
  規約 (`resolve_from` / `base_dir` / CWD から `<base>/<id>/<file>` を探索) で解決
  します。他方式は `package_resolver` を渡してください。
- **watch/reload なし** — ロード時にパースします。ライブリロードは変更時に
  `parse()` / `parse_file()` を再実行してください。
- **ストリーミングパーサーなし** — 入力全体をメモリに読み込みます。信頼できない入力は
  パース前にサイズを検証してください。

## セキュリティ上の考慮

信頼できない HOCON 入力をパースする際:

- **include のパストラバーサル:** `include "../../../etc/passwd"` は `base_dir`
  基準で解決されます。信頼できない入力ではパスを検証する `read_file` を渡してください。
- **入力サイズ:** 組み込みの上限はありません。信頼できない入力は `parse()` 前に
  サイズを検証してください。
- **include 深さ:** 深い include 連鎖によるスタックオーバーフローを防ぐため 50 段に
  制限しています。

## 開発

```sh
make setup      # .venv 作成 + dev 依存インストール (python3.11+ が必要)
make check      # ruff + mypy --strict + pytest
make bench      # マイクロベンチ実行
make testdata   # o3co/xx.hocon から conformance コーパスを同期
```

詳細は [CONTRIBUTING.md](CONTRIBUTING.md) を参照。

## ライセンス

Apache License 2.0 — [LICENSE](LICENSE) 参照。

Copyright 2026 1o1 Co. Ltd.

## Attribution

[Claude Code](https://claude.ai/claude-code) で end-to-end に設計・実装し、
[ts.hocon](https://github.com/o3co/ts.hocon) から移植しました。
