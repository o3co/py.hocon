# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project scaffold: package layout mirroring the sibling implementations
  (3-stage pipeline: Lexer → Parser → Resolver), error type hierarchy
  (`ParseError`, `ResolveError`, `PackageLookupError`, `ConfigError`,
  `NotResolvedError`), build/test tooling (hatchling, pytest, mypy, ruff),
  and the xx.hocon conformance-fixture sync target (`make testdata`).
