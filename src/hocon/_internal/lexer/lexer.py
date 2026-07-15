"""Tokenizer. Mirrors ts.hocon ``src/internal/lexer/lexer.ts``.

Python ``str`` is pre-decoded Unicode at the I/O boundary (same as JS), so the
byte-level decisions in go.hocon / rs.hocon do not apply here; S1.1 is
per-impl out of scope for the same reason as ts.hocon.
"""
