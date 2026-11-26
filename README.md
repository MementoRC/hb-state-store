# hb-state-store

[![CI](https://github.com/MementoRC/hb-state-store/actions/workflows/ci.yml/badge.svg)](https://github.com/MementoRC/hb-state-store/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Stdlib-only persistent state store (sqlite3 + file lock) for hummingbot sub-packages.

## Overview

`state_store` is an L0 leaf under ADR 0001 with zero runtime dependencies: it uses only
the Python standard library, never imports `hummingbot`, and never imports another
sub-package.

> **Scaffold notice**: the package currently contains only the version stub. The store
> implementation will be added in follow-up feature PRs.

## Installation

This package is distributed through conda-forge channels and managed with pixi:

```bash
pixi add hb-state-store
```

## Development

```bash
# Clone and install the dev environment
git clone https://github.com/MementoRC/hb-state-store.git
cd hb-state-store
pixi install

# Run tests
pixi run test

# Run quality checks
pixi run quality

# Run the full check suite
pixi run check
```

## Layout

```
hb-state-store/
  state_store/        # package (stdlib only)
    __about__.py      # version (managed by release-please)
    __init__.py
  tests/
  scripts/            # conda-first dependency gate
  pyproject.toml      # pixi manifest + tool config
  pixi.lock
```

## Branch Strategy

- `development`: active development branch (default for PRs)
- `main`: release tagging only; PRs to `main` must come from `development`
