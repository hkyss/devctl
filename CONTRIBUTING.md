# Contributing

## Ground rules

Everything runs in containers. There is no host Python environment to set up,
and you should not create one — `make` shells into the devctl image for every
check, so what you run locally is what CI runs.

Default branch is `dev`. Branch from it, open the PR against it.

## Setup

```bash
git clone https://github.com/hkyss/devctl
cd devctl
make install && make boot && make doctor
```

`make doctor` tells you what is missing. If it is unhappy about the workspace
root, devctl expects sibling repos under one parent directory (default
`~/Projects/Github/`, override with `DEVCTL_WORKSPACE_ROOT`).

## Before you push

```bash
make check   # compile, ruff lint, ruff format --check, example profile validation
make test    # unit tests
```

Both are what CI runs, so a green pair locally means a green PR. To apply
formatting rather than just check it:

```bash
docker compose -f .docker/docker-compose.yml run --rm --entrypoint sh devctl \
  -c 'cd "$DEVCTL_REPO_ROOT" && ruff format .'
```

Rebuild the image after changing source, or the CLI keeps running the old code:

```bash
make build
```

## Code style

- Ruff with `E,F,I,UP,B,SIM`, line length 140. Config lives in `pyproject.toml`.
- No comments and no docstrings. If a piece of code needs explaining, the
  explanation belongs in `docs/` or in a name that makes the comment redundant.
- Tests are plain `unittest`, one file per command or module, named `test_*.py`
  under `tests/`.

## Changing the profile format

`.devctl.json` is a public contract — other repositories depend on it. Any
change to it means updating all three of:

- `schemas/devctl.profile.schema.json`
- the validation rules in `src/devctl/standard.py`
- the examples in `examples/profiles/`

Adding a field is fine. Renaming or removing one is a breaking change and needs
a major version.

## Releases

Maintainers only:

```bash
devctl release minor      # or major / patch / an explicit X.Y.Z
```

This tags and pushes; CI runs the checks and publishes the GitHub Release. The
version is baked into the image at build time, so run `make build` afterwards.

## Reporting bugs

Include the output of `devctl doctor`, your `.devctl.json`, and the exact
command you ran. Local Docker setups differ enough that a report without them
is usually not actionable.
