# inspect_step

[English](README.md) | [Русский](README-ru.md)

`inspect_step` is an interactive strategy plugin for debugging Ansible playbooks and roles before each task is executed. It extends Ansible's `linear` strategy.

Current version: **1.0.0**.

Technical compatibility: **ansible-core 2.12–2.13**.  
Primary tested version: **ansible-core 2.13.13**.

## Main features

- display the current task source before deciding whether to run it;
- run, skip, or continue without further normal task stops;
- run to task-name, role, or tag breakpoints with `go`;
- inspect variables, nested paths, patterns, host-specific values, and task arguments;
- evaluate `when` conditions before execution and compare Jinja results across task hosts;
- explicitly evaluate a trusted lookup expression once for one selected host;
- preview host-specific loop items and `loop_control` metadata without executing the task;
- evaluate an expression, `when`, templated arguments, or a template for one selected loop item;
- inspect the previous task result with optional depth limiting;
- automatically display watched Jinja expressions at each stop;
- preview an `ansible.builtin.template` result on screen or save it locally before execution;
- limit the display depth of large mappings and sequences;
- temporarily change a variable for all play hosts or one selected host;
- explicitly ignore an unhandled task failure and continue the playbook;
- mask common secret keys in safe inspection commands;
- command history and line editing through Python `readline` when available.

## Requirements

- `ansible-core >= 2.12.0, < 2.14`;
- a Python version supported by the installed Ansible release;
- interactive standard input for command-line editing.

At startup, the plugin reports the detected Ansible version. Versions older than 2.12 produce a partial-compatibility warning because inspection commands that need task variables may be unavailable. Version 2.14 or newer stops immediately with a clear incompatibility error instead of failing later in an internal strategy API.

## Quick start

Copy `strategy_plugins/inspect_step.py` into your Ansible project and configure the plugin path:

```ini
[defaults]
strategy_plugins = ./strategy_plugins
```

Select the strategy in a play:

```yaml
---
- name: Debug application role
  hosts: web
  strategy: inspect_step

  roles:
    - application
```

Run the playbook with `--step`:

```bash
ansible-playbook -i inventory playbook.yml --limit web01 --step
```

At startup, the plugin prints `inspect_step version 1.0.0` and the Ansible compatibility status. Before each executable task it displays the task definition and opens the `inspect-step>` prompt.

## Essential commands

```text
r | run                         run the current task
s | skip                        skip the current task
c | continue                    run and disable normal task stops
g | go                          run until a configured breakpoint
w                               display the current task again
hosts                           list play hosts after --limit
vars|v [SELECTOR] [host=HOST] [depth=N]
                                inspect variables with masked secrets
vars!|v! [SELECTOR] [host=HOST] [depth=N]
                                inspect variables without masking
set NAME VALUE [host=HOST]      temporarily change a variable
e | eval JINJA [host=HOST]      evaluate a composite Jinja string
eval-lookup JINJA [host=HOST]   evaluate once with lookups enabled
eval-all JINJA [diff=true]      evaluate for every current task host
when [HOST|all]                 preview current when conditions
loop [HOST|all] [depth=N]       preview loop items with masking
loop eval ITEM JINJA [host=HOST]
loop when|args|template ITEM [host=HOST]
                                inspect one loop item without executing it
result [HOST|all] [depth=N]     inspect the previous result
watch add JINJA [host=HOST]     add an expression watch
break task REGEX                add a task-name breakpoint
args                            display templated task arguments
raw                             display original task arguments
template [HOST]                 preview a rendered template
template-save FILE [HOST]       save a rendered template locally
h | help | ?                    display command help
```

`vars` is the primary command name and `v` is its complete short alias. `SELECTOR` may be an exact name, a dotted path, a glob, or an explicit regular expression such as `regex=^role_.*$`. Optional `host=HOST` and `depth=N` parameters work identically with both names. The `!` suffix explicitly disables masking.

After an unhandled task failure, `inspect-failure>` offers `i | ignore` to continue with the current step setting, `c | continue` to continue without normal task stops, or `a | abort` to preserve standard Ansible failure behavior.

## Check mode

Use Ansible check and diff modes together with the inspector when you want modules to predict changes before a normal run:

```bash
ansible-playbook -i inventory playbook.yml --limit web01 --check --diff --step
```

The prompts and commands remain available. `r`, `c`, and `g` queue tasks with `ansible_check_mode=True`; `s` does not invoke the task at all. A `changed` result means “would change” only when the module implements check mode correctly. Unsupported modules may be skipped or return incomplete registered data. Check mode is not a security boundary: `check_mode: false`, controller-side lookups including `eval-lookup`, `template-save`, custom plugins, caches, and logging can still have real effects. See the detailed user guide before relying on `--check`.

## Documentation

- [Detailed user guide](UserGuide.md)
- [Русское руководство пользователя](UserGuide-ru.md)
- [Architecture diagrams](diagramms/)
- [Russian technical overview presentation](presentation/inspect-step-technical-overview-ru.md) ([PowerPoint](presentation/inspect-step-technical-overview-ru.pptx))
- [Changelog](CHANGELOG.md)
- [Русская история изменений](CHANGELOG-ru.md)
- [Runnable two-host example](example/)

## Security notice

Secret masking is heuristic. `eval`, `eval-lookup`, `eval-all`, watches, `raw`, `vars!`, `v!`, `loop!`, `result!`, `args!`, and template preview commands can expose sensitive data, and values entered with `set` remain in the current process's readline history. `vars` and its short alias `v` mask secrets by default. Ansible lookup plugins are disabled for `eval`, `eval-all`, `loop eval`, and watches. `eval-lookup` deliberately enables them for one selected host and prints a warning before every evaluation; a lookup runs on the controller and may read files, invoke commands, access external systems, or cause side effects. Evaluating `when`, templating task arguments, or previewing a loop, selected loop item, or template follows normal Ansible templating and can also execute lookups present in the task. Ignoring a task failure changes its recap status but does not undo remote-side changes made before the failure. Review the security section of the user guide before using the inspector with production systems or secrets.

## License

[MIT](LICENSE)
