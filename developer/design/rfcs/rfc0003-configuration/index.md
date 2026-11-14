# RFC 0003 Configuration

|                  |                                                                                                                  |
| ---------------- | ---------------------------------------------------------------------------------------------------------------- |
| **Status**       | Draft                                                                                                            |
| **Created**      | 2026-11-14                                                                                                       |
| **Roadmap item** | [Migrate off OmegaConf](https://updates2mqtt.rhizomatics.org.uk/developer/design/roadmap/#migrate-off-omegaconf) |

## Summary

Updates2MQTT is pinned to `omegaconf>=2.3.0,<2.4.0`, because OmegaConf 2.4.0 broke startup when `MQTT_USER` isn’t set. This RFC looks at four ways forward:

1. Upgrade to OmegaConf 2.4
1. Become a full Hydra app
1. Move to Pydantic Settings
1. Move to another established config library

**Recommendation**

- **Now (small):** upgrade to OmegaConf 2.4 with a three-line compatibility fix, so we’re on the supported release line again.
- **Next (medium):** migrate to `pydantic-settings`, with a compatibility layer that keeps existing config files and env vars working.
- **Don’t:** adopt Hydra. It’s built for composing and sweeping experiment configs, not for running a long-lived daemon. Its stable releases can’t run on OmegaConf 2.4 yet, and it has had a string of high-severity advisories this year.

## Background

### How configuration works today

- `config.py` defines 16 dataclasses, loaded with `OmegaConf.structured()`. The config file `conf/config.yaml` is merged on top, the result is made read-only, and code reads it by attribute (`cfg.mqtt.host`).

- **Env vars** are read with OmegaConf interpolation in dataclass defaults, e.g. `host: str = "${oc.env:MQTT_HOST,localhost}"`. Only 19 settings have an env var. Everything else needs the config file (the Home Assistant area, for example).

- **Typing workarounds.** An interpolation string is a `str` default for an `int`, `bool` or enum field, so 6 fields carry `type: ignore` for mypy and `ty: ignore` for ty.

- **Auto-generated config.** If there’s no config file and the env vars don’t fully describe the config, the app writes one with `OmegaConf.to_yaml()`. That file contains the unresolved interpolations, for example:

  ```yaml
  mqtt:
    user: ${oc.env:MQTT_USER,???}
    port: ${oc.decode:${oc.env:MQTT_PORT,1883}}
  ```

  So **users’ config files contain OmegaConf syntax that we wrote for them.** The documentation and `examples/config.yaml.minimal` also tell users to write `${oc.env:...}` themselves. Any replacement must keep reading these files.

  These files also fix `node.name` to the hostname at the time the file was generated. That’s a side issue, but worth fixing in any migration.

  - **Placeholder detection.** `???` (`MISSING`) is the default for `mqtt.user`. If it stays missing, the app logs that the config “has place holders” and stops cleanly.
  - **Other uses:**
  - `common_packages.yaml` is loaded into the `CommonPackages` structured config in `docker_enrich.py`.
  - The `u2m-cli` debug tool parses `key=value` arguments with `OmegaConf.from_cli()`. Its `mqtt=check` command reports each setting and its env var by reading the unresolved interpolations.

| Where                                                                           | OmegaConf references |
| ------------------------------------------------------------------------------- | -------------------- |
| `src/updates2mqtt/cli.py`                                                       | 25                   |
| `src/updates2mqtt/config.py`                                                    | 6                    |
| `src/updates2mqtt/integrations/docker_enrich.py`                                | 6                    |
| `tests/` (7 files, mostly `OmegaConf.structured(MqttConfig)` in `test_mqtt.py`) | 182                  |

### Goals

These come from the roadmap.

- G1: Use a live, popular config library with timely security fixes and good documentation.
- G2: Make configuration consistent across env vars and files, so every setting can be set by env var, automatically.
- G3: Make config problems easy to debug and report clearly.
- G4 (value add): Support CLI args consistent with the env vars and config file.
- G5 (value add): Integrate with Vault or similar secret storage.
- G6: Keep full backward compatibility with existing env vars and config files. Auto-migration is optional, and can’t assume write access.
- G7: Work well in Docker/Podman, as a PyPI library, and as a systemd/init.d daemon.

## Option 1: Upgrade to OmegaConf 2.4

### State of OmegaConf

OmegaConf has come back to life. After the original author left Meta at the end of 2021, development slowed; 2.3.0 (December 2022) was the last release for three and a half years. In 2026 the author returned as maintainer. Hydra moved from Meta to the independent `hydra-ecosystem` GitHub organization ([announcement, 2026-08-13](https://hydra.cc/blog/2026/08/13/independent-stewardship/)), and OmegaConf followed.

| Release  | Date                            |
| -------- | ------------------------------- |
| 2.3.0    | 2022-12-08                      |
| 2.3.1    | 2026-06-11 (packaging fix only) |
| 2.4.0    | 2026-10-09                      |
| 2.4.1rc2 | 2026-10-28 (pre-release)        |

- About 38M downloads a month.
- 29 open issues and 2 open PRs.
- No published security advisories.
- PyPI lists three maintainers, but the 2026 activity is mainly one person.
- PyPI flags a “change of provenance” on 2.4.0, because the publishing workflow changed.

### What 2.4 changes

From the [2.4 upgrade guide](https://omegaconf.cli.dev/docs/migration/2.4):

- **Missing values (this is what broke us):**
  - Resolving an interpolation to `???` now raises `InterpolationToMissingValueError`. In 2.3 it silently left the value missing.
  - A resolver that returns plain `???` is now missing on access.
- Typed interpolations are validated on access.
- Implicit conversions on assignment emit a `FutureWarning`.
- `DictConfig`/`ListConfig` are unhashable, tuples become `TupleConfig`, and `OmegaConf.create(None)` returns `None`.
- Backslash escaping in `from_cli`/dotlist keys (2.4.0) and new path escaping (2.4.1rc2). These affect `u2m-cli` only.
- **Good things:**
  - Enums can be assigned by member name or value.
  - Better `Literal`/union typing.
  - The antlr runtime is vendored, ending its version conflicts.
  - YAML alias-expansion limits against crafted input.
  - Python 3.10 to 3.14 is supported.

### What we found by testing

I ran the full test suite against OmegaConf 2.4.0 in a throwaway environment, outside the repo.

- **Unchanged code:**
  - 46 tests failed and 18 errored.
  - Every one was the same `InterpolationToMissingValueError` on `mqtt.user`, from the `${oc.env:MQTT_USER,???}` default.
  - No `FutureWarning` or other change showed up, even with `-Werror`.
- **With the `mqtt.user` default changed to `${oc.env:MQTT_USER,''}`:**
  - Everything passed on both 2.3.1 and 2.4.0 except one test.
  - That test, `test_check_mqtt_missing_user_skips_connect`, needs `u2m-cli mqtt=check` to treat an empty user as missing as well as `???`.
  - The app’s own check already treats `""` and `???` the same.
- **Existing auto-generated config files** (containing `user: ${oc.env:MQTT_USER,???}`):

| OmegaConf | `MQTT_USER` set | `MQTT_USER` not set                                                                  |
| --------- | --------------- | ------------------------------------------------------------------------------------ |
| 2.3.1     | Loads           | Logs “place holders”, app stops cleanly                                              |
| 2.4.0     | Loads           | **Uncaught `InterpolationToMissingValueError`, so startup crashes with a traceback** |

`InterpolationToMissingValueError` is an `InterpolationResolutionError`. `load_app_config()` only catches `MissingMandatoryValue` and `ValidationError`, so this needs one more `except` that maps it to the same placeholder outcome.

### Work and impact

- **Work:** about half a day.
  - Change the `mqtt.user` default.
  - Catch `InterpolationResolutionError` in `load_app_config()` (and the CLI equivalent) as “placeholder”.
  - Treat `""` as missing in `u2m-cli`.
  - Widen the pin to `>=2.4.0,<2.5`.
  - Add a regression test for a legacy auto-generated file with `MQTT_USER` unset.
- **User impact:** none if the `except` is added. Without it, the only users affected are those with an old auto-generated file and no `MQTT_USER`. Their install isn’t configured yet anyway, but they’d get a crash instead of a clear message.

### Against the goals

| Goal | Fit                                                                                            |
| ---- | ---------------------------------------------------------------------------------------------- |
| G1   | ⚠️ Revived and releasing again, but with a short recent track record and mainly one maintainer |
| G2   | ❌ Env vars still have to be wired up field by field with `oc.env`. Nothing generates them     |
| G3   | ⚠️ Errors give the full key path. Interpolation errors are hard for users to read              |
| G4   | ❌ `from_cli()` takes dotlists only, with no help or validation of names                       |
| G5   | ❌ None. A custom resolver could fetch secrets                                                 |
| G6   | ✅ Same file format                                                                            |
| G7   | ✅                                                                                             |

**Verdict:** worth doing now as a holding move, because it gets us off a pin to an old release line cheaply. It doesn’t meet G2, G4 or G5.

## Option 2: Become a full Hydra app

### What Hydra adds

[Hydra](https://hydra.cc/docs/intro/) is built on OmegaConf. It adds:

- composing config from config groups with a `defaults` list
- command-line overrides with tab completion
- `--multirun` sweeps
- launcher and sweeper plugins (Ray, Submitit, Optuna, etc.)
- per-run output directories
- configuration of Python logging
- `hydra.utils.instantiate()` to build objects from config
- an `@hydra.main` entry point, or the `compose` API for apps that don’t use `@hydra.main`

### State of Hydra

- Latest stable is `hydra-core` 1.3.8 (2026-10-25). 1.4.0 is at rc3 (2026-10-25).
- Mostly one maintainer, with about 17M downloads a month.
- **Version coupling:**
  - hydra-core 1.3.8 resolves only to OmegaConf 2.3.1.
  - 1.4.0rc3 requires OmegaConf 2.4.1rc2, which is a pre-release.
  - So no stable Hydra release runs on OmegaConf 2.4 today. Adopting Hydra would mean either staying on OmegaConf 2.3 or depending on pre-releases.
- **Security:** seven advisories published between July and October 2026, six of them high severity. Most concern `instantiate()`, its target blocklist, unsafe YAML loading, and callables resolved from logging config. Of the 1.x line, only 1.4 claims Python 3.13/3.14 support.

### Fit for Updates2MQTT

Hydra’s features target ML and research workflows: composing variants, sweeping parameters, launching jobs, keeping per-run outputs. A home-automation daemon in a container needs none of these.

What it costs:

- **`@hydra.main` takes over the process.** It owns argument parsing, configures logging (we use structlog), and by default creates per-run output directories. Each of these can be switched off, but that means fighting the framework.
- **The `compose` API avoids that,** but then we’d get only config-group composition, which we have no use for.
- **Env vars** still come only from OmegaConf’s `oc.env`, so G2 is no better than option 1.
- It adds a framework-sized dependency, with a recent advisory history, to the software that pulls and restarts containers on users’ hosts.

| Goal | Fit                                                                                          |
| ---- | -------------------------------------------------------------------------------------------- |
| G1   | ⚠️ Active again, but mainly one maintainer and recent high-severity advisories               |
| G2   | ❌ Same as OmegaConf                                                                         |
| G3   | ⚠️ Same as OmegaConf                                                                         |
| G4   | ✅ Strong CLI overrides, but in Hydra’s `key=value` grammar, not flags matching the env vars |
| G5   | ❌                                                                                           |
| G6   | ✅ Reads the same files                                                                      |
| G7   | ⚠️ Working-directory, logging and output-directory defaults all need disabling for a daemon  |

**Verdict:** not recommended.

## Option 3: Move to Pydantic Settings

### State of Pydantic Settings

- [`pydantic-settings`](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/) 2.16.3 was released 2026-11-13, its tenth release of 2026. It’s maintained by the Pydantic organization, with Trusted Publishing and provenance.
- About 488M downloads a month, which is 13× OmegaConf.
- We already use it in `anpr2mqtt`.
- It requires Python ≥3.11, and we require ≥3.13.

### How it meets the goals

- **Env vars for everything (G2).** With `env_prefix="U2M_"` and `env_nested_delimiter="__"`, every field gets an env var automatically, e.g. `U2M_MQTT__HOST`, `U2M_HOMEASSISTANT__AREA` or `U2M_DOCKER__REGISTRY__API`.
- **Legacy env vars (G6).** `validation_alias=AliasChoices("U2M_MQTT__HOST", "MQTT_HOST")` accepts either name, and the first one found wins. Every one of today’s 19 env var names can stay as an alias.
- **YAML file.** `YamlConfigSettingsSource`. Source priority is set with `settings_customise_sources`, e.g. CLI, then env, then secrets, then file, then defaults.
- **Validation (G3).**
  - Errors from Pydantic’s `ValidationError` give each field’s path and the reason.
  - Setting `PYDANTIC_SETTINGS_DEBUG=1` logs what each source supplied, which answers “where did this value come from?”
- **CLI (G4).** `cli_parse_args` / `CliApp` generate flags from the same model, e.g. `--mqtt.host`. `cli_show_env_vars` lists the matching env var in `--help`.
- **Secrets (G5).**
  - `secrets_dir` covers Docker/Podman secrets, one file per field.
  - Built-in sources cover AWS Secrets Manager and SSM, Azure Key Vault, and GCP Secret Manager.
  - HashiCorp Vault isn’t built in, but a custom source is a small class.
- **Typing.** Real types with no interpolation strings, so the six `type: ignore` / `ty: ignore` workarounds go away.

### Gotchas to design around

- **Partial updates of nested models.** By default, setting one nested field from an env var *replaces* that nested model’s defaults wholesale. We need `nested_model_default_partial_update=True`.
- **Unknown env vars.** Env vars that match no field are silently ignored, even with `extra="forbid"`. Keep and extend the unrecognised-env-var warning added in 1.17.6: derive the known `U2M_*` names from the model instead of keeping a hand-maintained list.
- **Case.** Env var matching is case-insensitive by default. Set `case_sensitive=True` for predictable behaviour.
- **Lists.** List and dict values from env vars are parsed as JSON. Selectors such as `image_ref_select.exclude` need either JSON or a `NoDecode` annotation with a comma-split validator.
- **Aliases on nested models.** Aliases on nested models need `populate_by_name` (or `validate_by_name`), so the field name is accepted alongside the alias.
- **Stricter JSON matching.** Pydantic 2.14.2 treats keys that match only an unused alias as extra data in JSON validation. This needs a test.

### Backward compatibility layer

This is the part that makes the migration safe for existing installs.

1. **Legacy YAML interpolation.**
   - Add a custom YAML settings source. Before validating, it resolves the small OmegaConf subset that we generate and document:
     - `${oc.env:VAR}`
     - `${oc.env:VAR,default}` with quoted or bare defaults, including `null` and `''`
     - `${oc.decode:...}` wrapped around them
     - a bare `???`
   - That’s a regex-sized resolver of about 50 lines, not a dependency on OmegaConf.
   - Anything else in `${...}` form is a clear validation error that names the key.
   - Optionally log a one-time hint that the file can now use plain values.
1. **Legacy env var names.**
   - Every existing name, e.g. `MQTT_HOST`, `MQTT_PASS` or `U2M_LOG_LEVEL`, becomes an `AliasChoices` entry next to the new `U2M_SECTION__KEY` name.
   - Precedence: when both are set, the new name wins.
   - Add a test with one row per legacy name.
1. **Placeholder detection.** Keep it: an `mqtt.user` that is missing or empty gives the same “place holders” outcome.
1. **Auto-generated config.**
   - Stop writing resolved defaults and the hostname into the generated file.
   - Write a commented template instead, or a file holding only what’s needed.
   - Existing generated files keep working through point 1.
1. **No rewriting of user files.** We can’t assume write access (G6). A `u2m-cli config=migrate` command can print a cleaned-up file for users to copy if they want one.

### Work

| Area                                                                        | Estimate         | Notes                                                                                       |
| --------------------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------- |
| `config.py` dataclasses become `BaseModel`, `Config` becomes `BaseSettings` | 1 day            | Attribute access (`cfg.mqtt.host`) stays the same, so most of `src/` is untouched           |
| Legacy YAML resolver source and tests                                       | 1 day            | Includes tests against every example and doc snippet, and a real auto-generated 1.17 file   |
| Legacy env var aliases and tests                                            | 0.5 day          |                                                                                             |
| `common_packages.yaml` loading with a Pydantic model                        | 0.5 day          | No env vars needed. Errors must still name the package                                      |
| `u2m-cli`: replace `from_cli()` and the settings report                     | 1 day            | The report can come from the model and source data instead of parsing interpolation strings |
| Tests: replace `OmegaConf.structured(...)` fixtures                         | 1 day            | Mostly mechanical, about 180 references, concentrated in `test_mqtt.py`                     |
| Docs: config pages, env var tables, examples, FAQ                           | 1 day            | Env var tables can be generated from the model                                              |
| **Total**                                                                   | **about 6 days** |                                                                                             |

**New dependencies:** `pydantic`, `pydantic-core` (a compiled wheel), `pydantic-settings[yaml]`, `annotated-types` and `typing-inspection`. `omegaconf` and its vendored antlr runtime are removed. `pydantic-core` has wheels for the Docker image’s architectures, but check the image-size change.

**User impact:** none expected if the compatibility layer lands. New installs get documented `U2M_SECTION__KEY` env vars for every setting. The old names stay supported for at least two minor releases. After that, whether to deprecate them (with a startup warning first) is a separate decision.

| Goal | Fit                                                                                                  |
| ---- | ---------------------------------------------------------------------------------------------------- |
| G1   | ✅ Highest adoption and release cadence of any option, run by an organization rather than one person |
| G2   | ✅ Automatic env vars for every field                                                                |
| G3   | ✅ Field-path errors and source debugging. Unknown env vars need our own warning                     |
| G4   | ✅ Generated CLI with env var names shown in help                                                    |
| G5   | ⚠️ Docker secrets and the main cloud secret stores are built in. Vault needs a small custom source   |
| G6   | ✅ With the compatibility layer above                                                                |
| G7   | ✅                                                                                                   |

## Option 4: Other established libraries

| Library                                                  | Latest                             | Health                                                                      | Notes                                                                                                                                                                                                                                                        |
| -------------------------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [Dynaconf](https://www.dynaconf.com/)                    | 3.3.5 (2026-08-05)                 | ⚠️ Releasing again in 2026 after a two-year gap, about 5M downloads a month | Strongest built-in Vault and Redis support. Env vars with `__` nesting. But validation is lazy (on first access), the settings object is global and mutable, typed models are only a tech preview, and there’s no CLI matching the env vars                  |
| [typed-settings](https://typed-settings.readthedocs.io/) | 26.1.0 (2026-11-05)                | ⚠️ Active, but one maintainer and a much smaller user base                  | Good design: works with attrs, dataclasses or Pydantic, and generates CLIs with argparse or Click. But 27.0 will break internal and advanced APIs, the default `_` delimiter collides with field names, and secrets support is aimed at 1Password, not Vault |
| [jsonargparse](https://jsonargparse.readthedocs.io/)     | Not confirmed (docs show 5.0.0rc2) | ✅ Active, and the base of PyTorch Lightning’s CLI                          | Clearest precedence from defaults through file and env vars to CLI. But it’s CLI-first, env vars must be switched on explicitly, and its interpolation is powered by OmegaConf                                                                               |
| [confz](https://pypi.org/project/confz/)                 | 2.1.0 (2025-02-07)                 | ❌ No release for 21 months                                                 | Pydantic-based. Nested env vars use `.`, which shells and Compose handle badly                                                                                                                                                                               |
| msgspec, cattrs                                          | 0.22.0, 26.2.1                     | ✅                                                                          | Serialization and validation libraries, not config loaders. Could underpin a hand-rolled loader, but that means owning env var and CLI handling ourselves                                                                                                    |
| environ-config                                           | Not assessed                       | -                                                                           | Its PyPI page couldn’t be fetched                                                                                                                                                                                                                            |

None of these beats Pydantic Settings on G1 to G4 together, and the one with clearly better Vault support (Dynaconf) is weaker on typing and validation. Dynaconf is only worth reconsidering if Vault becomes a hard requirement.

## Recommendation and plan

1. **Phase 0, the next point release:** upgrade to OmegaConf 2.4 as described in [option 1](#option-1-upgrade-to-omegaconf-24). This removes the pin to a stale release line and has no user impact.
1. **Phase 1, the next minor release:** migrate to `pydantic-settings` with the [compatibility layer](#backward-compatibility-layer).
   - Document the `U2M_SECTION__KEY` env vars.
   - Generate the env var reference from the model.
   - Fold in deferred settings, e.g. `U2M_HOMEASSISTANT__AREA`.
1. **Phase 2, later:**
   - Generated CLI flags for `u2m-cli`.
   - A Vault settings source if users ask for one.
   - Decide whether to deprecate the legacy env var names.
1. **Not planned:** Hydra.

## Open questions

- Prefix for new env vars: `U2M_` (short, already used by four settings) or `UPDATES2MQTT_` (clearer, but used by out-of-date guides with different meanings)? This RFC assumes `U2M_`.
- Should the legacy `${oc.env:...}` resolver stay permanently, or warn and eventually go? Users copied this syntax from our own docs, so it may be kindest to support it permanently.
- Is a TOML config file worth offering next to YAML? Pydantic Settings supports both, but YAML is what Home Assistant users expect.
- `mqtt.port` and `log.level` use `oc.decode` today. Check that nothing else in user files relies on `oc.decode` turning strings into lists or dicts.

## References

- OmegaConf [2.4.0 release notes](https://github.com/hydra-ecosystem/omegaconf/releases/tag/v2.4.0), [2.4 upgrade guide](https://omegaconf.cli.dev/docs/migration/2.4), [missing values](https://omegaconf.cli.dev/docs/concepts/missing-values), [built-in resolvers](https://omegaconf.cli.dev/docs/reference/built-in-resolvers), [PyPI](https://pypi.org/project/omegaconf/)
- Hydra [introduction](https://hydra.cc/docs/intro/), [independent stewardship](https://hydra.cc/blog/2026/08/13/independent-stewardship/), [security advisories](https://github.com/hydra-ecosystem/hydra/security/advisories), [PyPI](https://pypi.org/project/hydra-core/)
- [Pydantic Settings documentation](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/), [PyPI](https://pypi.org/project/pydantic-settings/)
- [Dynaconf](https://www.dynaconf.com/), [typed-settings](https://typed-settings.readthedocs.io/), [jsonargparse](https://jsonargparse.readthedocs.io/), [confz](https://pypi.org/project/confz/)
- Download figures from [pypistats.org](https://pypistats.org), November 2026
