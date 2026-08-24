# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-21

### Added

- Interactive `inspect_step` strategy based on the Ansible 2.13 `linear` strategy and native `--step` flow.
- Task execution controls: `r`/`run`, `s`/`skip`, and `c`/`continue` without further stops.
- Post-failure prompt for explicitly ignoring an unhandled task failure and continuing the play for affected hosts.
- Automatic masked task source preview and the `w` command for repeating it.
- Unified safe `vars` command with the complete `v` short alias: exact names, nested mapping/JSON/sequence paths, globs, explicit `regex=REGEXP`, `host=HOST`, `depth=N`, and explicitly unmasked `vars!`/`v!` forms.
- Host-aware inspection and a command that lists play hosts after inventory and `--limit` processing.
- Original and templated task argument inspection with safe and explicitly unmasked modes.
- Composite Jinja expression evaluation for the default or an explicitly selected host, with structured output and Ansible lookups disabled.
- Explicit one-host `eval-lookup` evaluation with Ansible lookups enabled, a warning before every call, structured unmasked output, and no watch or cross-host mode.
- Cross-host Jinja evaluation with optional difference collapsing through `eval-all`.
- Pre-execution evaluation of `when` conditions for one host or all current task hosts.
- Host-aware preview of modern `loop` and legacy `with_*` items, including `loop_control` metadata, depth limiting, and masked or explicitly unmasked output.
- One-item loop context for evaluating a Jinja expression, `when`, templated task arguments, or a template without executing the item.
- Host-aware, depth-limited inspection of the previous task result with masked and explicitly unmasked modes.
- Process-local expression watches automatically displayed at interactive stops.
- Task-name regular-expression, exact role, and exact tag breakpoints with `go` execution.
- Host-specific preview of `ansible.builtin.template` results on screen or in a protected local file.
- Recursive heuristic masking for common secret key names.
- Runtime top-level variable changes for all play hosts or one selected host.
- Readline command history and cursor-based line editing when available.
- Runnable two-host example for facts, role variables, `set_fact`, `register`, templates, handlers, different loop items per host, `loop_control`, conditions, and a tagged breakpoint target.
- English and Russian README files, detailed user guides, changelogs, and PlantUML architecture diagrams.
- Complete English and Russian documentation of `--check` behavior, predicted results, unsupported modules, controller-side effects, and inspector command semantics.
- Startup version output: `inspect_step version 1.0.0`.
- Startup compatibility check with a supported-range status, a partial-compatibility warning for versions older than 2.12, and a clear incompatibility error for 2.14 and newer.

### Fixed

- Single or double quotes around breakpoint values are now treated as grouping syntax instead of literal pattern characters.
