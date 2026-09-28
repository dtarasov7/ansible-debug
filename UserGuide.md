# `inspect_step` User Guide

[English](UserGuide.md) | [Русский](UserGuide-ru.md)

This guide describes installation, daily use, variable inspection, runtime variable changes, security considerations, and troubleshooting for `inspect_step` version 2.1.0.

## 1. Purpose

`inspect_step` is a custom Ansible strategy plugin for interactive debugging. It pauses before an executable task is queued, shows what is about to run, and lets the operator inspect the task context before choosing an action.

The plugin is useful when you need to:

- understand which task is about to execute;
- explicitly inspect the result of one task that normally uses task-level `no_log`;
- compare variables for multiple hosts selected by `--limit`;
- inspect facts, role variables, registered results, and `set_fact` values;
- inspect original and templated task arguments;
- evaluate a composite Jinja string against variables of a selected host;
- preview conditions, compare expressions across hosts, and inspect prior results;
- expand host-specific loop items and inspect loop-control metadata;
- browse the current play's task/include tree and select exact breakpoints by task ID;
- track selected expressions and run to task, role, or tag breakpoints;
- render an `ansible.builtin.template` source before execution and view or save the result;
- reduce the output of very large nested variable structures;
- temporarily override a variable without editing inventory or playbook files;
- skip one task or continue the rest of the play without normal task pauses.

The plugin extends Ansible's `linear` strategy. Inventory processing, variable precedence, templating, task execution, handlers, loops, conditions, delegation, tags, and result processing remain Ansible responsibilities.

## 2. Supported environment

| ansible-core | Standalone file / strategy name |
| --- | --- |
| 2.12–2.13 | `inspect_step.py` / `inspect_step` (unchanged) |
| 2.14–2.18 | `inspect_step_2_14.py` / `inspect_step_2_14` |
| 2.19–2.20 | `inspect_step_2_19.py` / `inspect_step_2_19` |
| 2.21 | `inspect_step_2_21.py` / `inspect_step_2_21` |

Files are in `strategy_plugins/` and are standalone. Copy the matching file and select the strategy from the table. For newer versions, replace `strategy: inspect_step` in the examples below with the matching name. New variants reject versions outside their range; the original file is unchanged. See [tests/README.md](tests/README.md) for tested versions and commands.

Python must be compatible with the installed Ansible release. Python's standard `readline` module is optional; it is required only for interactive history and cursor-based line editing.

## 3. Execution model

For each lockstep task, the plugin determines the active hosts and chooses the first one as the default inspection host. It then:

1. obtains task variables through Ansible's `VariableManager`;
2. prints the task name and host context;
3. renders the original task definition with common secret keys masked;
4. evaluates configured watches and opens the `inspect-step>` command loop;
5. waits for `run`, `run!`, `skip`, `go`, or `continue`;
6. lets the inherited `linear` strategy queue and execute the task;
7. captures the processed per-host result for inspection at a later prompt.

If an executed task returns an unhandled failure, the plugin opens a separate `inspect-failure>` prompt before Ansible removes the failed hosts from the remaining play. The operator can explicitly treat that failure as ignored or preserve the standard failed state.

With multiple active hosts, the prompt appears once for the lockstep task, not once per host. `run` executes the task for the active host group according to normal `linear` behavior.

## 4. Installation

Place the plugin in a strategy plugin directory inside the Ansible project:

```text
project/
├── ansible.cfg
├── inventory
├── playbook.yml
└── strategy_plugins/
    └── inspect_step.py
```

Configure the directory in `ansible.cfg`:

```ini
[defaults]
strategy_plugins = ./strategy_plugins
```

The relative path is resolved from the directory where `ansible-playbook` is started. If you run Ansible from another directory, use a correct relative path or an absolute path.

Select the strategy in the play:

```yaml
---
- name: Debug application deployment
  hosts: web
  strategy: inspect_step

  roles:
    - application
```

## 5. Starting an interactive run

Use the plugin together with Ansible's `--step` option:

```bash
ansible-playbook -i inventory playbook.yml --limit web01 --step
```

Debugging one host is the simplest mode because facts, inventory variables, registered results, and runtime facts can differ between hosts.

To debug a group or several hosts:

```bash
ansible-playbook -i inventory playbook.yml --limit 'web01,web02' --step
```

or:

```bash
ansible-playbook -i inventory playbook.yml --limit web --step
```

At strategy initialization, the following line is printed once per `ansible-playbook` process:

```text
inspect_step version 2.1.0
Ansible compatibility: ansible-core 2.13.13 is the primary tested version (technical range 2.12-2.13).
```

Without `--step`, the strategy behaves like `linear` and does not open the inspector prompt. The version and compatibility status are still displayed when the strategy is initialized.

## 6. Prompt and task preview

A normal stop looks like this:

```text
INSPECT TASK: application : Configure service
Host: web01 (inspection host; task has 2 active hosts)

TASK SOURCE [/project/roles/application/tasks/main.yml:12] (secrets masked)
- name: Configure service
  ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app/app.conf

inspect-step>
```

The task has not executed when the prompt is displayed. The source preview is generated from Ansible's parsed task data. YAML layout, quoting, and indentation can differ from the source file, and source comments are not preserved.

Implicit tasks such as `Gathering Facts` may not have original parsed task data. In that case the warning below is expected and does not affect execution:

```text
[WARNING]: Original task definition is unavailable
```

## 7. Command summary

| Command | Purpose | Secret masking |
|---|---|---|
| `r`, `run` | Execute the current task | Not applicable |
| `r!`, `run!` | Execute the current task with task-level `no_log` disabled | Disabled intentionally |
| `ra`, `run-all` | Execute a dynamic include and all descendants, then resume task stops | Not applicable |
| `s`, `skip` | Skip the current task | Not applicable |
| `c`, `continue` | Execute the current task and disable later normal task stops | Not applicable |
| `g`, `go` | Execute tasks until a configured breakpoint matches | Not applicable |
| `w` | Display the current task source again | Enabled |
| `hosts` | List play hosts after inventory and `--limit` | Not applicable |
| `vars`, `v`, `var` + `[NAME\|PATH\|glob=PATTERN\|regex=REGEXP\|JINJA_EXPRESSION] [host=HOST] [depth=N]` | Display variables and evaluate expressions | Heuristic; computed scalars can reveal secrets |
| `vars!`, `v!`, `var!` + `[NAME\|PATH\|glob=PATTERN\|regex=REGEXP\|JINJA_EXPRESSION] [host=HOST] [depth=N]` | Same command without masking | Disabled intentionally |
| `set NAME YAML_VALUE [host=HOST]` | Change a top-level variable in memory | Value is not echoed |
| `e JINJA_EXPRESSION [host=HOST]` | Evaluate a composite Jinja string; alias for `eval` | Disabled |
| `eval JINJA_EXPRESSION [host=HOST]` | Evaluate a composite Jinja string with lookups disabled | Disabled |
| `eval-lookup JINJA_EXPRESSION [host=HOST]` | Evaluate once for one host with Ansible lookups enabled | Disabled |
| `eval-all JINJA_EXPRESSION [diff=true]` | Evaluate an expression for all hosts active on the current task | Disabled |
| `when [HOST\|all]` | Evaluate the current task's conditions before execution | Not applicable |
| `loop [HOST\|all] [depth=N]` | Preview loop items and loop-control metadata | Enabled |
| `loop! [HOST\|all] [depth=N]` | Preview loop items without secret masking | Disabled intentionally |
| `loop eval ITEM EXPRESSION [host=HOST]` | Evaluate a Jinja expression in one selected item context | Disabled |
| `loop when ITEM [host=HOST]` | Evaluate task conditions for one selected item | Not applicable |
| `loop args ITEM [host=HOST]` | Display templated arguments for one selected item | Enabled |
| `loop template ITEM [host=HOST]` | Render the template for one selected item | Disabled intentionally |
| `result [HOST\|all] [depth=N]` | Display the previous executed task result | Enabled |
| `result! [HOST\|all] [depth=N]` | Display the previous result without masking | Disabled intentionally |
| `watch add EXPRESSION [host=HOST]` | Add an expression displayed at each stop | Disabled |
| `watch list`, `watch delete ID` | List or delete expression watches | Not applicable |
| `tasks [tree] [host=HOST] [regex=REGEXP] [role=NAME] [tag=TAG]` | Browse statically known and runtime-expanded tasks | Not applicable |
| `break pick TASK_ID` | Add an exact breakpoint for a task-browser entry | Not applicable |
| `break task REGEX` | Stop `go` when a task name matches the regular expression | Not applicable |
| `break role NAME`, `break tag TAG` | Stop `go` on an exact role name or tag | Not applicable |
| `break list`, `break delete ID` | List or delete breakpoints | Not applicable |
| `a`, `args` | Display templated task arguments | Enabled |
| `args!` | Display templated task arguments | Disabled intentionally |
| `raw` | Display original `task.args` | Disabled |
| `template [HOST]` | Render the current template task and display its resulting content | Disabled intentionally |
| `template-save LOCAL_PATH [HOST]` | Render and save the result on the controller | Disabled intentionally |
| `h`, `help`, `?` | Display built-in help | Not applicable |

The failure prompt has its own commands:

| Command | Purpose |
|---|---|
| `i`, `ignore` | Ignore failures from the current task and preserve the current step-mode setting |
| `c`, `continue` | Ignore failures from the current task and disable later normal task stops |
| `a`, `abort` | Keep standard Ansible failure behavior for affected hosts |

An unknown inspector command or an inspection operation error does not terminate the playbook. The inspector remains on the current task and waits for another command. This statement does not mean that an executed Ansible task failure is ignored automatically; the failure must be handled by the playbook or explicitly accepted through `inspect-failure>`.

## 8. Controlling task execution

### Run the current task

```text
inspect-step> r

RUN: application : Configure service
```

`run` is equivalent to `r`. The next executable task opens another prompt while step mode remains enabled.

### Run with task-level `no_log` disabled

```text
inspect-step> r!

[WARNING]: task-level no_log is disabled for this task; results and secrets may
be written to stdout and callback logs

RUN (no_log disabled): application : Read protected value
```

`run!` is equivalent to `r!`. The override applies to every active host and loop item of this selected task. The inspector queues a copy with the same UUID and `no_log: false`; it does not mutate the original task or disable `no_log` for following tasks.

This command bypasses task-level `no_log` only. A module can independently sanitize arguments marked `no_log` in its argument specification, and those values can remain replaced with `VALUE_SPECIFIED_IN_NO_LOG_PARAMETER`. A controller-wide `DEFAULT_NO_LOG` setting is also outside this task-level override. Treat terminal output, callback plugins, job logs, and stored events as secret-bearing after using `r!`.

### Run a dynamic include completely

At an `include_tasks` or `include_role` prompt, use `ra` or `run-all` to execute the dynamic include and its complete descendant tree without intermediate task prompts:

```text
inspect-step> ra

RUN ALL: application : Load platform tasks
```

Nested dynamic includes and include loops remain inside the selected scope. Handlers synchronously invoked by `flush_handlers` inside the scope also run without a task prompt. The first executable task outside that include displays `RUN ALL COMPLETE` and opens the normal prompt again. Breakpoints and watches do not stop inside the scope because no normal prompts are opened there; an unhandled failure can still open `inspect-failure>`.

The existing commands retain their meanings at a dynamic include: `s` skips the complete include before it is expanded, while `r` expands it and then stops on every included task. `run-all` is rejected for ordinary tasks and static `import_tasks` or `import_role` statements.

### Skip the current task

```text
inspect-step> s

SKIP: application : Restart service
```

`skip` is equivalent to `s`. For a lockstep task, it skips the task for the current active host group.

The inspector opens one decision prompt for every explicit `ansible.builtin.meta` task, even though ansible-core normally excludes meta actions from `--step`. One decision applies to the complete active lockstep host group: `r` executes the action with its normal Ansible semantics, while `s` skips it for the group. For example, skipping `end_play` proceeds to the next task, while running it ends the play. Implicit `noop`, `flush_handlers`, and `role_complete` tasks created by Ansible remain hidden and execute normally.

### Continue without normal task stops

```text
inspect-step> c

RUN: application : Configure service
```

`continue` is equivalent to `c`. The current task runs, and the rest of the play proceeds without normal task-inspection stops. A post-failure prompt can still appear for an unhandled failure so the operator can decide whether affected hosts should continue.

### Run to a breakpoint

First browse tasks when names, roles, or include structure are not known in advance:

```text
tasks
tasks tree
tasks tree host=web02 role=application
tasks regex='(?i)configure|restart'
tasks tag=deployment
break pick 12
go
```

`tasks` assigns numeric IDs stable within the current play and displays `CURRENT`, `REACHED`, or `PENDING` for the selected inspection host. `REACHED` means that the iterator reached the task, including a task skipped in the inspector; it does not mean successful execution. `host=HOST` selects this status view but cannot predict future `when` conditions or host-dependent dynamic includes. The tree form preserves compiled role and include nesting. A filtered tree keeps matching tasks plus their include ancestors so the context remains visible. `regex` uses Python substring search; `role` and `tag` are exact and case-sensitive.

Static imports and roles are compiled before strategy execution, so their descendants are visible immediately. Their synthetic import group is marked `static import; group only` and cannot receive a breakpoint because no runtime stop exists at that node. Dynamic `include_tasks` and `include_role` nodes are marked `dynamic; not expanded`; their descendants are added to the same tree after Ansible expands them. Until then, those runtime task IDs do not exist.

`break pick TASK_ID` binds to the selected task's internal runtime UUID instead of its display name. This distinguishes duplicate names and is the safest way to target one concrete task. Task IDs and picked breakpoints apply to the current play.

Define one or more breakpoints, then use `g` or `go`:

```text
break task 'Exercise a loop'
break role application
break tag deployment
break list
go
```

`break task` applies a Python regular expression to the full task name and uses substring search. It is a regexp, not a glob: `*` repeats the preceding regexp item and cannot appear at the beginning. Consequently, `*application*` is invalid and produces `nothing to repeat`. To find a word anywhere in the name, use the word itself:

```text
break task application
```

`.*application.*` also works, but the surrounding `.*` is redundant because regexp `search` already scans the complete name.

Task-name regexp examples:

| Goal | Command |
|---|---|
| Name contains `application` | `break task application` |
| Case-insensitive search | `break task '(?i)application'` |
| Name starts with a role prefix | `break task '^test_role : Render'` |
| Name ends with `configuration` | `break task 'configuration$'` |
| Either of two tasks | `break task 'Exercise (a loop\|a condition)'` |
| Arbitrary text between words | `break task 'Render.*configuration'` |
| Literal dot | `break task 'version 1\.2'` |
| Literal `*` character | `break task 'file \* generated'` |

The full name of a role task commonly looks like `test_role : Exercise a loop`, so `^` and `$` anchors must account for the role prefix. Use `w` to see the current task name and source definition.

The complete breakpoint value may be enclosed in single or double quotes; these grouping quotes are removed and do not become part of the expression. Quotes are optional because the remainder of the input line is treated as one value, so `break task Exercise a loop` and `break task 'Exercise a loop'` are equivalent. Role and tag breakpoints use exact, case-sensitive matching rather than regexp and accept the same quoting. Breakpoints receive numeric IDs and can be removed with `break delete ID`.

`go` executes the current task and suppresses ordinary prompts until any breakpoint matches. The matching task has not executed when `BREAKPOINT HIT` and its normal inspector prompt appear. `go` is rejected if no breakpoint exists. Use `c` when no later interactive stop is wanted. Failure inspection remains active while `go` is running.

### Behavior with Ansible check mode

The inspector can be combined with Ansible check and diff modes:

```bash
ansible-playbook -i inventory playbook.yml \
  --limit 'web01,web02' --check --diff --step
```

`inspect_step` does not implement a separate simulation engine. It preserves Ansible's check-mode context and forwards approved tasks to the normal executor. The task header, source preview, prompt, host selection, watches, and breakpoints behave as in a normal step run. Confirm the effective mode from any prompt with:

```text
v ansible_check_mode
eval {{ ansible_check_mode }}
```

Both commands should print `True` for a `--check` run.

Execution commands have the following meaning:

| Command | Behavior under `--check` |
|---|---|
| `r`, `run` | Queue the current task with `ansible_check_mode=True`; a supporting module predicts its result |
| `r!`, `run!` | Same as `run`, but disable task-level `no_log` for the selected check-mode result |
| `s`, `skip` | Do not queue the task at all; no prediction or registered result is produced by that task |
| `c`, `continue` | Queue the current and later tasks in check mode and disable later normal prompts |
| `g`, `go` | Queue tasks in check mode until a breakpoint matches; the matching task is still stopped before execution |
| `result`, `result!` | Display the previous real check-mode result; `changed` normally means “would change” |

Normal Ansible check-mode rules still apply:

- modules with check-mode support inspect current state and predict `ok`, `changed`, `skipped`, or failure without applying the managed-host change;
- modules without support may be skipped or return incomplete data, so registered variables and later conditions can differ from a normal run;
- facts can still be gathered, and `set_fact` can update variables inside the current controller process so later simulated tasks can use them;
- `changed_when` and `failed_when` are evaluated against the check-mode result when enough result data exists;
- a predicted changed task can notify a handler; the handler is also processed in check mode unless its task overrides the mode;
- syntax, undefined-variable, argument-validation, connectivity, privilege, template, and explicit `fail` errors can still fail a task;
- `--diff` adds predicted before/after content for modules such as `template` and `copy` when they support it.

Inspector commands execute on the controller and are not automatically neutralized by `--check`:

- `w`, `hosts`, `v`, `vars`, `raw`, `result`, breakpoint management, and watch management only inspect or update debugger state;
- `eval`, `eval-all`, `loop eval`, and watches continue to block Ansible lookup plugins;
- `set` really changes the inspector's non-persistent in-memory variables for the current run, although it does not write inventory or variable files;
- `eval-lookup` performs the actual lookup, including a Vault, command, file, DNS, or network lookup, and can have external side effects;
- `args`, `when`, `loop`, `template`, `loop when`, `loop args`, and `loop template` use normal Ansible templating and can execute lookups embedded in a task or template;
- `template` does not write the remote destination, but reads and renders controller-side template data;
- `template-save` really creates a protected local controller file even under `--check` and never overwrites an existing file.

Ansible check mode is therefore a prediction aid, not a transaction or security boundary. A task with `check_mode: false` is explicitly forced to run normally even when the playbook was started with `--check`. Action plugins, lookup plugins, callbacks, fact caches, logging, custom modules, and external services can also have real controller-side or external effects. A module may implement check mode incompletely, and mutable external data can change between preview and the later normal run.

The ordinary `inspect-failure>` workflow remains active for failures produced during check mode. Ignoring such a failure only changes Ansible's controller-side state and recap for the current run. It does not make a task safe and cannot undo a real effect caused by `check_mode: false`, a lookup, a plugin, or controller-side file creation.

### Continue after a task failure

When a task executed with `r`, `run`, `r!`, `run!`, `c`, or `continue` fails and the failure is not already handled by `ignore_errors` or `block`/`rescue`, the plugin displays:

```text
INSPECT FAILURE: application : Configure service
Failed host: web01
The decision applies to failures from this task on 2 active hosts.

inspect-failure>
```

Choose one of the following actions:

- `i` or `ignore` — convert failures from this task to ignored results and continue. The existing normal step-mode setting is preserved.
- `c` or `continue` — convert the failures to ignored results, continue the playbook, and disable later normal `inspect-step>` stops.
- `a` or `abort` — keep Ansible's normal failed state. Failed hosts are removed from subsequent ordinary tasks.

The choice is made once and applies to every active host that fails the same task. A host that successfully completed the task is not modified. When a failure is ignored, the recap reports `failed=0` and increments `ignored` for the restored hosts. The original `fatal` callback remains visible because the choice is made after the task result has been received.

The failure prompt remains available during a run that started with `--step`, even if normal task prompts were previously disabled with `c`. This allows a failure to be handled after an unattended portion of the play.

The feature does not intercept unreachable results. It also does not replace existing Ansible error handling: `ignore_errors` continues automatically, while `block`/`rescue` follows the rescue branch without an additional failure prompt.

## 9. Repeating the task and listing hosts

After a long variable dump, use `w` to display the current task again:

```text
inspect-step> w
```

Use `hosts` to see the hosts selected for the current play after applying inventory and `--limit`:

```text
inspect-step> hosts
HOSTS IN CURRENT PLAY (--limit applied)
  web01 (default inspection host, active for current task)
  web02 (active for current task)
```

A host can belong to the play without being active for the current task. The labels make this distinction explicit.

## 10. Unified `vars` command and `v`/`var` aliases

`vars` is the primary variable-inspection command. `v` and `var` are short aliases: all three use the same parser, options, and masking rules. Use `vars!`, `v!`, or `var!` to disable masking.

### All task variables

```text
inspect-step> vars
VARIABLES [web01]
{...}
```

The values come from Ansible's `VariableManager` for the current play, host, and task. This includes the variable sources and precedence that Ansible normally exposes: role defaults and vars, inventory and group/host vars, play/task vars, facts, registered results, `set_fact`, extra vars, and magic variables.

The short alias produces the same result:

```text
v
v depth=1
```

### Exact names and nested paths

```text
vars app_port
v app_config.workers
vars json_settings.limits.connections
v application_servers.0.address
```

Dot notation traverses mappings and decoded JSON objects. Numeric path components index lists and tuples. A string containing valid JSON object or array data is decoded before path traversal and formatted output. For keys with characters outside a variable name, use Jinja brackets, for example `v app_config['foo-bar']`.

The host label is always printed. By default, the inspection host from the task header is used. Select another host only with an explicit `host=NAME` option:

```text
vars app_port host=web02
v app_port host=web02 depth=1
```

The positional form `vars app_port web02` is not supported because it is ambiguous when a hostname is also a variable name.

### Jinja expressions

Enter an expression with Ansible filters, functions, or multiple variables after the command name. The `{{ }}` delimiters are optional:

```text
var app_password | length
vars app_config.workers + 2
v [app_root, app_config.workers] | to_json
set tg test
v groups[tg]              # members of group test
v groups[tg][0]           # first host: test01
```

The expression uses the selected host's variables. The usual `host=HOST` and `depth=N` options are available. Lookup plugins are disabled. Mapping keys are masked as usual, but a computed scalar can reveal a secret; avoid printing secrets through expressions.

### Globs and regular expressions

A glob is a simple pattern for matching variable names. Prefix it with `glob=` so the inspector knows you want a name search. It checks complete top-level names only:

```text
v glob=role_*       # role_name, role_port: * matches zero or more characters
v glob=*port*       # app_port, role_port: port anywhere in the name
v glob=role_?       # role_a, but not role_ab: ? matches exactly one character
v glob=role_[ab]    # role_a and role_b: [ab] matches one listed character
```

Without `glob=`, brackets are Jinja indexing. For example, `v groups[tg][0]` gets the first host from the group named by `tg`. Operators are also evaluated as Jinja expressions: `v a*b` multiplies two variables. The previous `v role_*` syntax must be changed to `v glob=role_*`.

For Python regular expressions, use the separate `regex=` prefix. The expression must match the complete top-level name:

```text
vars regex=^application_.*$
v regex=^(role|application)_[a-z0-9_]+$
```

Glob and regexp searches display all matching values together; neither searches nested keys.

### Undefined values and invalid regular expressions

An inspection error does not terminate the playbook and returns to the current prompt:

```text
Variable 'missing_name' is undefined
Variable path 'app_config.missing_key' is undefined
Invalid variable regexp: nothing to repeat at position 0
```

## 11. Depth, `hostvars`, and secret masking

### Limit output depth

Facts can make a complete variable dump extremely large. A positive `depth=N` option collapses nested containers and works identically with `vars`, `v`, and `var`:

```text
vars depth=1
v depth=2 host=web02
vars ansible_facts depth=1
v ansible_facts.python depth=2 host=web02
```

Depth is counted from the selected root:

- `vars depth=1` displays the first level of the complete variable mapping;
- `vars app_config depth=1` displays the first level inside `app_config`;
- `v app_config.limits depth=1` displays the first level inside `limits`.

Collapsed values use summaries such as:

```text
<mapping: 93 keys>
<list: 4 items>
<tuple: 2 items>
```

The selector, `host=HOST`, and `depth=N` may appear in any order, each at most once. `depth` must be a positive integer. Without `depth`, the selected value is displayed completely.

### `hostvars`

Without `host=HOST`, the command preserves standard Ansible behavior and displays the mapping for all hosts available through `hostvars`:

```text
vars hostvars
```

An explicit host selects the corresponding `hostvars` entry:

```text
v hostvars host=web02
vars hostvars.ansible_facts host=web02
```

The host name can also be included directly in the path:

```text
vars hostvars.web02.ansible_facts.python.version
```

### Secret masking

`vars`, `v`, and `var` recursively replace values whose keys contain common secret markers such as `password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, or `private_key`:

```text
'database_password': '*** HIDDEN ***'
```

Disabling masking must always be explicit. `vars!`, `v!`, and `var!` are also complete aliases:

```text
vars! app_config host=web02 depth=2
v! app_config host=web02 depth=2
```

## 12. Inspecting expressions, loops, task arguments, and templates

### Original arguments

`raw` displays `task.args` before Jinja and Ansible variable substitution:

```text
inspect-step> raw
{'msg': 'service port is {{ app_port }}'}
```

This command does not mask secrets.

### Templated arguments

`args`, or its short alias `a`, templates the arguments using variables for the default inspection host:

```text
inspect-step> args
{'msg': 'service port is 8080'}
```

Common secret keys are masked recursively. Use `args!` to disable masking explicitly.

The alias `a` is available at the ordinary `inspect-step>` prompt. At `inspect-failure>`, `a` keeps its separate meaning: abort and preserve the Ansible failure.

Argument inspection is diagnostic only. It uses normal Ansible templating, so a lookup embedded in the task arguments can execute on the controller during preview and again when the task runs. The Ansible task executor performs the authoritative templating and validation.

### Evaluating a composite expression

Use `eval` or its short alias `e` at any ordinary `inspect-step>` prompt. Everything after the command name is treated as a Jinja template string:

```text
inspect-step> eval {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf
EVAL [web01] =
/tmp/application-web01.conf
```

The default is the inspection host shown in the task header. To use variables of another host in the current play, add `host=HOST` as the final argument:

```text
inspect-step> e {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf host=web02
EVAL [web02] =
/tmp/application-web02.conf
```

Jinja filters, tests, conditionals, mappings, and sequences are supported. A mapping, sequence, or JSON result is pretty-printed:

```text
eval {{ app_config }} host=web02
eval {{ app_port | int + 100 }} host=web02
eval {{ 'enabled' if feature_enabled else 'disabled' }}
```

Undefined variables produce a warning and return to the same prompt. Ansible lookup plugins are deliberately disabled, so expressions such as `{{ lookup('file', '/path') }}` are rejected instead of reading files, invoking commands, or accessing external systems from the controller.

The result is not secret-masked because `eval` is an explicit request for an effective value. It can therefore expose sensitive data, including data used by a task with `no_log`.

### Evaluating an explicit lookup expression

Use `eval-lookup` when the expression must call an Ansible lookup plugin. Without `host=HOST`, it uses the inspection host shown in the task header. A trailing `host=HOST` selects one other host in the current play:

```text
eval-lookup {{ lookup('env', 'HOME') }}
eval-lookup {{ query('fileglob', '/etc/*.conf') }} host=web02
```

For example, if the `hashi_vault` lookup plugin is installed and its connection and authentication settings are available to Ansible, a host-specific Vault expression can be inspected with:

```text
eval-lookup {{ lookup('hashi_vault', hashicorp_vault_hashi_vault_path_root + (hashicorp_vault_cacertfile | basename)) }} host=test01
```

The command evaluates the expression once for exactly one selected host and never expands it to `all`. It is not available through `eval-all` and cannot be added to watches. A mapping, sequence, or JSON string is pretty-printed. An undefined variable, missing lookup plugin, authentication error, or plugin error is reported and returns control to the same prompt.

Before every evaluation, the inspector prints an explicit warning. Lookup plugins run on the controller, not on the selected managed host, and may read controller files, invoke commands, access the network or external systems, or cause side effects. Running the task later can execute the same lookup again and can produce a different result. The output is not secret-masked, including results returned from Vault and values protected by task `no_log`.

### Comparing an expression across hosts

`eval-all` evaluates the same expression for every host active on the current task:

```text
inspect-step> eval-all {{ app_port }}
EVAL [web01] =
8081
EVAL [web02] =
8082
```

Add `diff=true` as the final option to collapse identical successful values:

```text
eval-all {{ app_config }} diff=true
```

If all values are equal, the inspector prints `no differences` and one value. Otherwise it prints every host value. An evaluation error is reported per host and does not leave the current prompt. Lookups are disabled, and results are not secret-masked.

### Previewing `when`

Use the same Ansible conditional evaluator that will decide whether the current task runs:

```text
when
when web02
when all
```

The default is the inspection host; `all` selects all hosts active on the current task. Each condition is shown as `TRUE`, `FALSE`, or `ERROR`, followed by the overall `RUN`, `SKIP`, or `ERROR` decision. Conditions after the first false condition are marked `NOT EVALUATED` to preserve Ansible's short-circuit behavior. A task without conditions reports `RUN (no conditions)`.

Unlike `eval`, this command intentionally follows Ansible's normal conditional semantics. A lookup explicitly present in a task's `when` expression can therefore run on the controller during preview and run again when the executor evaluates the task.

### Previewing loop items

On a task with `loop` or legacy `with_*`, inspect the expanded items without executing the task:

```text
loop
loop test02
loop all
loop all depth=1
loop! test02 depth=2
```

The default is the inspection host. A named host selects that play host, and `all` displays a separate preview for every host active on the current task. Host-specific variables can therefore produce different item counts and values. `depth=N` is measured from each item root.

The preview shows:

- whether the source is `loop` or a legacy `with_*` lookup;
- the number of expanded items;
- the effective `loop_var`;
- a zero-based `index_var`, when configured;
- whether extended loop metadata is enabled;
- the rendered `loop_control.label`, when configured;
- every expanded item in execution order.

For example:

```text
LOOP PREVIEW [test02]: 3 items
  source: loop
  loop_var: item
  index_var: loop_index (zero-based)
  extended: true
  ITEM 1/3
  loop_index = 0
  label =
'alpha'
  item =
'alpha'
```

`loop` recursively masks common secret-key names in structured items. `loop!` explicitly disables masking. Masking remains heuristic: scalar secrets or custom labels with unrelated names can still be displayed.

The command uses the same supported Ansible templating and lookup mechanisms as task execution. Consequently, a lookup in `loop`, `query`, or legacy `with_*` can read files, invoke commands, or access external systems on the controller during preview and can run again during actual task execution. The inspector displays a warning before evaluation. Lookup results may also change between preview and execution.

The plain `loop` preview does not execute a loop item, template the task arguments for each item, populate `register`, notify handlers, or change recap statistics. The inspector still opens one ordinary prompt for the complete task rather than one prompt per item.

### Evaluating one selected loop item context

After `loop` preview, select an item by its 1-based `ITEM N/M` number and run one diagnostic operation:

```text
loop eval 2 {{ item }}:{{ template_index }}:{{ ansible_loop.last }} host=test01
loop when 2 host=test01
loop args 2 host=test01
loop template 2 host=test01
```

Without `host=HOST`, the default inspection host is used. There is no `all` mode: one command builds one item context for one host. The context includes the effective `loop_var`, configured zero-based `index_var`, `ansible_loop_var`, and extended `ansible_loop` metadata when `loop_control.extended` is enabled.

- `loop eval` evaluates a Jinja expression with Ansible lookups disabled; its result is unmasked;
- `loop when` applies the current task's real conditions and displays the final `RUN` or `SKIP` decision;
- `loop args` templates `task.args` and masks common secret-key names;
- `loop template` works on a looped `ansible.builtin.template` task and displays unmasked rendered content.

Every command expands the loop again. A lookup in the loop or legacy `with_*`, conditions, arguments, or template can therefore run on the controller and can run again during actual task execution. The inspector warns about this risk, and diagnostic output can differ from the later execution.

The item is not executed: no partial result, `register`, handler notification, or recap change is created. Use `r` to execute the complete loop task; per-item run and skip remain unsupported.

#### Complete demonstration sequence

The bundled example contains the loop task `test_role : Render loop-aware application configuration` with two items, `primary` and `disabled`. Start the playbook for both test hosts:

```bash
cd example
ansible-playbook -i inventory playbook.yml \
  --limit 'test01,test02' \
  --step
```

At the first stop, add a breakpoint and continue to the demonstration task:

```text
inspect-step> break task '^test_role : Render loop-aware application configuration$'
BREAKPOINT #1 added

inspect-step> g
GO: running until a breakpoint matches
```

After the breakpoint matches, expand the loop for both hosts:

```text
inspect-step> loop all
```

The inspector displays two items and the zero-based `template_index` for each host:

```text
ITEM 1/2
  template_index = 0
  item = 'primary'

ITEM 2/2
  template_index = 1
  item = 'disabled'
```

Evaluate an expression in the first item context for `test02`:

```text
inspect-step> loop eval 1 {{ inventory_hostname }}:{{ item }}:{{ template_index }}:{{ ansible_loop.first }} host=test02
```

Expected result:

```text
LOOP ITEM CONTEXT [test02] ITEM 1/2
  item =
'primary'
EVAL [test02] =
test02:primary:0:True
```

A composite path is evaluated in the same context:

```text
inspect-step> loop eval 1 {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}-{{ item }}.conf host=test02
EVAL [test02] =
/tmp/inspect-test-test02-primary.conf
```

Evaluate `when` for the first item:

```text
inspect-step> loop when 1 host=test02
  1. TRUE: item != "disabled"
WHEN [test02]: RUN
```

Inspect the templated task arguments:

```text
inspect-step> loop args 1 host=test02
{'dest': '/tmp/inspect-test-test02-primary.conf', 'mode': '0640', 'src': 'loop-application.conf.j2'}
```

Render the template without executing the item or writing the remote destination:

```text
inspect-step> loop template 1 host=test02
TEMPLATE PREVIEW [test02]
Destination: /tmp/inspect-test-test02-primary.conf
----- BEGIN TEMPLATE -----
# Generated for inspect_step loop item preview
host=test02
profile=primary
profile_index=0
first=True
destination=/tmp/inspect-test-test02-primary.conf
----- END TEMPLATE -----
```

The second item demonstrates a context in which the condition prevents execution:

```text
inspect-step> loop eval 2 {{ item }}:{{ template_index }}:{{ ansible_loop.last }} host=test02
EVAL [test02] =
disabled:1:True

inspect-step> loop when 2 host=test02
  1. FALSE: item != "disabled"
WHEN [test02]: SKIP
```

Even after the `SKIP` decision, `loop args 2 host=test02` and `loop template 2 host=test02` can diagnostically inspect the templating result. They do not bypass the condition or execute the item.

To finish the demonstration without executing the loop task, use:

```text
inspect-step> s
inspect-step> c
```

To execute the complete loop task normally, use `r`: the `primary` item runs and `disabled` is skipped by `when`.

### Inspecting the previous task result

At the next task prompt, inspect the most recently processed task result:

```text
result
result web02 depth=2
result all depth=1
result! all
```

The output includes the previous task name, host, and derived status: `ok`, `changed`, `skipped`, `failed`, `unreachable`, or `ignored`. The default is the current inspection host. `all` displays every host captured for that previous task. `depth=N` uses the same root-relative container limiting as `vars`.

`result` masks common secret-key names recursively and omits Ansible's private `_ansible_*` transport fields. `result!` explicitly disables secret masking. Before the first task has completed, the command reports that no previous result is available.

### Watching expressions

Watches automatically evaluate expressions immediately after the task source is displayed at each interactive stop:

```text
watch add {{ app_port }}
watch add {{ hostvars[inventory_hostname].host_color }} host=web02
watch list
watch delete 1
```

Without `host=HOST`, a watch follows the default inspection host of each stop. With a host, it remains pinned to that active play host. Watches have process-local numeric IDs and disappear when `ansible-playbook` exits. Lookup plugins are disabled, but watch values are unmasked and can expose secrets. Watches are not evaluated for tasks skipped over by `go`, because those tasks do not create an interactive stop.

### Previewing an `ansible.builtin.template` result

On a task that uses `ansible.builtin.template`, render the source for the default inspection host without executing the task:

```text
inspect-step> template
TEMPLATE PREVIEW [web01]
Source: /project/roles/application/templates/app.conf.j2
Destination: /etc/application/app.conf
----- BEGIN TEMPLATE -----
listen_port=8080
node=web01
----- END TEMPLATE -----
```

With several active hosts, specify the host to render with its own variables:

```text
template web02
```

Save the exact rendered bytes to a local file on the Ansible controller:

```text
template-save previews/web02-app.conf web02
template-save "/tmp/preview files/web02-app.conf" web02
```

A relative `LOCAL_PATH` is resolved from the directory where `ansible-playbook` was started. The parent directory must already exist. To prevent accidental data loss, an existing file is never overwritten. A newly saved file is created with mode `0600`, and the task's `output_encoding` setting is honored.

Rendering uses the task's action/module defaults, `src`, `dest`, Jinja delimiter, whitespace, newline, include search-path, and template metadata settings. It follows normal Ansible templating, so lookups in arguments or template content can execute on the controller during preview and again when the task runs. The preview is host-specific and does not write the remote `dest`; use `r` only when you are ready to execute the task.

The complete rendered content is intentionally not masked because masking would make the preview inaccurate. A warning is displayed before output or saving. This can reveal values even when the task uses `no_log`.

## 13. Changing variables at runtime

`set` creates or replaces a top-level variable through Ansible's non-persistent fact cache.

### Change a variable for all play hosts

The default scope is every host in the current play after `--limit`:

```text
set app_port 9000
set feature_enabled true
set deployment_mode blue
set app_config '{"workers": 4, "limits": {"connections": 200}}'
```

The response lists affected hosts but does not repeat the value:

```text
SET app_port for hosts: web01, web02
```

### Change a variable for one host

Use an explicit `host=HOST` option:

```text
set app_port 9002 host=web02
```

The host must be active in the current play.

### Value types and quoting

The value is parsed with YAML safe loading, so numbers, booleans, nulls, mappings, and sequences retain their data types. JSON is valid YAML and is convenient for structured values.

The whole command is one input line and follows shell-like quoting. To force a string that resembles a YAML boolean or number, preserve YAML quotes inside the command:

```text
set feature_mode '"true"'
set release_code '"0012"'
```

Variable names must match `[A-Za-z_][A-Za-z0-9_]*`. Nested assignments such as `set app_config.workers 8` are not supported; replace the top-level structure instead.

### Lifetime and precedence

The new value is available to `vars` (and its `v` and `var` aliases), to `args`, to the task currently waiting at the prompt, and to subsequent tasks. It is not written to inventory, variable files, or the playbook and disappears when the `ansible-playbook` process ends.

Later `set_fact` or registered results can replace a value. Extra vars supplied with `-e` and Ansible magic variables have higher precedence and cannot be overridden by this command.

## 14. Command history and line editing

When Python `readline` is available and standard input is an interactive terminal:

- ↑ and ↓ navigate command history;
- ← and → move the cursor;
- Backspace/Delete edit the current command;
- a recalled command can be modified and executed again.

History exists only in the current `ansible-playbook` process and is not saved between runs. With redirected input or a pipeline, commands can still be read, but terminal line editing is unavailable. If arrow keys print sequences such as `^[[A`, the terminal is not using readline for that prompt or the module is unavailable.

## 15. Recommended debugging workflow

1. Start with one host: `--limit web01 --step`.
2. Read the automatic task preview before entering an execution command.
3. Use `vars depth=1` for an overview after fact gathering.
4. Narrow the investigation with `vars NAME`, `v PATH depth=N`, a `glob=PATTERN` search, or an explicit `regex=REGEXP`.
5. Use `when all` and `eval-all JINJA diff=true` to compare host-specific decisions and values.
6. On a looped task, use `loop all depth=N` to compare expanded items before execution.
7. Use `args` to verify templated arguments and `result all depth=2` to inspect the previous task.
8. Add watches for values that must be tracked across several stops.
9. On an `ansible.builtin.template` task, use `template [HOST]` or `template-save FILE [HOST]` to inspect the resulting file.
10. If necessary, use `set` and immediately verify the effective value with `v`, `eval`, `args`, `loop`, or `template`.
11. Use `w` to restore task context after long output.
12. For a long run, define narrow breakpoints and use `go`; otherwise choose `r`, `s`, or `c`. Use `r!` only when exposing the selected task result is explicitly required.
13. If `inspect-failure>` appears, inspect the fatal result and explicitly choose `ignore`, `continue`, or `abort`.

For multiple hosts, run `hosts` first and explicitly add a host to inspection commands whenever host-specific values matter.

When module support is known, begin with `--check --diff --step`, treat `changed` as a prediction, and inspect it with `result`. Repeat the run without `--check` only after reviewing lookups, `check_mode` overrides, controller-side writes, and predicted diffs.

## 16. Security considerations

Masking is heuristic, not a security boundary. It recognizes key names containing a small list of common secret terms. Sensitive values stored under unrelated key names can still be printed.

Commands that mask common secret-key names by default:

- automatic task source preview;
- `w`;
- `vars`, `v`, and `var`;
- `loop`;
- `result`;
- `args`;
- the selected item printed before `loop eval`, `loop when`, `loop args`, or `loop template`;
- `loop args`.

Commands that can expose values without masking:

- `r!` and `run!`;
- `e` and `eval`;
- `eval-lookup`;
- `eval-all` and watches;
- `raw`;
- `vars!`, `v!`, and `var!`;
- `loop!`;
- `result!`;
- `args!`;
- `template` and `template-save`;
- `loop eval` and `loop template`.

`set` does not echo its value in the response, but the original command remains visible on the terminal and in readline history for the current process. Avoid entering production secrets when terminal output or session recording is not trusted.

Ansible `no_log` does not turn the inspector into a complete secret filter. `r!` deliberately disables task-level `no_log` for one selected task and can expose its result through every enabled callback. Module-level argument sanitization and controller-wide `DEFAULT_NO_LOG` are independent and may still hide output. Review task previews and diagnostic commands carefully.

`eval`, `eval-all`, `loop eval`, and watches disable Ansible lookup plugins to prevent their controller-side side effects. Jinja filters and tests, including project-provided extensions, still execute, so use only expressions you trust. `eval-lookup` is the explicit exception: it enables lookup plugins for one command and one host, prints a warning every time, and does not mask the result. `when`, loop preview, templated argument inspection, template preview, `loop when`, `loop args`, and `loop template` use normal Ansible evaluation, so an embedded lookup can run on the controller during preview.

`--check` does not strengthen these security properties. It only asks participating modules to predict managed-host changes. It does not suppress controller-side lookups, local preview files, plugin or callback behavior, caches, logging, or a task explicitly marked `check_mode: false`.

Ignoring a failure does not roll back changes that the failed module may already have made on a managed host. Use the recovery action only after assessing whether continuing leaves the system in a safe state.

## 17. Troubleshooting

### The plugin cannot be found

Check `strategy_plugins` in `ansible.cfg`, verify the working directory, and confirm that the play contains:

```yaml
strategy: inspect_step
```

### The version is printed but there is no prompt

Add `--step` to the `ansible-playbook` command. The plugin intentionally behaves like `linear` without step mode.

### A task is skipped or still has an effect under `--check`

Inspect `v ansible_check_mode` first. A skipped task may use a module without check-mode support; inspect its `result` and do not assume that its registered data matches a normal run. A reported `changed` is a prediction, not proof that a remote change occurred. If a real effect occurred, check for `check_mode: false`, controller-side lookups, `eval-lookup`, `template-save`, action or callback plugins, fact caches, logging, and custom module behavior. Use `--diff` where supported and repeat against a disposable target when an authoritative result is required.

### The playbook stops after a failed task

If the run was started with `--step`, use `i` at `inspect-failure>` to ignore failures from that task and continue debugging, or `c` to continue without normal task stops. Use `a` to preserve Ansible's failed state. Without `--step`, the plugin does not change normal Ansible error handling.

### `Original task definition is unavailable`

This is expected for synthetic Ansible tasks such as implicit fact gathering. Variable inspection and task execution remain available.

### Arrow keys print escape characters

Use an interactive terminal and verify that Python can import `readline`. Line editing is not available when stdin is redirected or piped.

### `vars` output is too large

Start with `vars depth=1`, then inspect a branch with `vars PATH depth=N` or a single value with `v PATH`.

### A variable or path is undefined

Run `vars depth=1` or a matching pattern such as `v glob=prefix_*` or `vars regex=^prefix_.*$` to confirm the top-level name. Remember that patterns search only top-level variable names.

### `eval` cannot calculate an expression

Check that every referenced variable exists for the host printed in `EVAL [HOST]`. Select another host with a trailing `host=HOST`. A lookup-related warning is expected because lookup plugins are intentionally disabled for this command.

### `eval-lookup` cannot calculate an expression

Check the host-specific variables first with `vars PATH host=HOST`, then verify that Ansible can resolve the lookup plugin and that its controller-side dependencies, configuration, credentials, files, and network access are available. For Vault lookups, an authentication or certificate error comes from the lookup plugin; the inspector reports it and stays at the same prompt. Use `host=HOST` only as the final `eval-lookup` option, and remember that the lookup runs on the controller even though variables come from the selected host.

### `go` does not start or stops too often

`go` requires at least one breakpoint. Use `break list` and remember that task breakpoints are regular expressions, while role and tag breakpoints are exact matches. Delete a broad rule with `break delete ID`.

### Loop preview reports an error or different items

Confirm that the current task defines `loop` or `with_*`, that the selected host has every referenced variable, and that the expanded modern `loop` value is a list. A lookup can return different data when it is evaluated again during actual execution. Use `loop all` to identify host-specific differences and `depth=N` to limit large item structures.

### `set` reports success but the effective value is unchanged

Check whether the name is an extra var (`-e`) or magic variable with higher precedence. Also check whether a later `set_fact`, registered result, role parameter, or include parameter replaces it.

### A structured `set` value is rejected

Use valid one-line YAML or JSON and quote it as one command-line value:

```text
set settings '{"enabled": true, "ports": [8080, 8081]}'
```

### Host selection is unexpected in `vars`

Host selection requires `host=HOST`. A bare hostname is part of the selector or expression; use `hostvars.web02` to inspect that host's data.

### A template preview cannot be rendered

Confirm that the current task uses `ansible.builtin.template`, that `src` exists in the normal Ansible template search path, and that every referenced variable is defined for the selected host. On a looped template task, the plain `template` command has no `item` value; use `loop template ITEM [host=HOST]`.

If `template-save` reports that the local file already exists, choose a new path. The command deliberately has no overwrite mode.

## 18. Limitations

- Use the file matching your ansible-core version in section 2; internal APIs differ between releases.
- Check-mode accuracy depends on each module and plugin; `changed` is a prediction, unsupported modules may skip, and registered values can differ from a normal run.
- `--check` does not suppress `check_mode: false`, controller-side lookup/plugin effects, in-memory `set` changes, or local files created by `template-save`.
- The inspector stops once per task, not once per loop item.
- Loop preview and item-aware commands do not provide per-item execution, skipping, retries, or result registration.
- A lockstep task produces one prompt for its active host group.
- `when` preview is diagnostic; the executor evaluates the condition again after `run`, so mutable state or lookups can produce a different decision.
- Every explicit meta task opens one inspector prompt for its active lockstep host group; implicit meta and noop lifecycle tasks created by Ansible do not open a prompt.
- `run-all` is limited to dynamic `include_tasks` and `include_role`; static imports are expanded before strategy execution and cannot open an import-level prompt.
- `r!` disables task-level `no_log` only for the selected task; it cannot reverse sanitization already performed by a module or override controller-wide `DEFAULT_NO_LOG` consistently.
- Source rendering normalizes YAML and omits source comments.
- `set` changes only top-level variables and is not persistent.
- Inspection commands, watches, and breakpoint management are available at ordinary pre-task `inspect-step>` prompts, not at the post-failure decision prompt.
- Lookup plugins are disabled for `eval`, `eval-all`, `loop eval`, and watches; these commands still evaluate variables, Jinja operators, filters, tests, mappings, and sequences.
- `eval-lookup` evaluates one expression for one play host; it has no `all`, watch, or automatic `eval-all` mode, and its unmasked result may differ when the task evaluates the lookup again.
- Loop preview uses normal Ansible templating and can execute controller-side lookup plugins.
- Templated argument and template previews can execute controller-side lookups embedded in the task or template.
- Watches and breakpoints live only for the current `ansible-playbook` process.
- Template preview supports the built-in `template`, `ansible.builtin.template`, and `ansible.legacy.template` action names; unrelated collection actions named `template` are not assumed to be compatible.
- The plain `template` command does not create loop variables; use `loop template ITEM` to build a diagnostic context for one selected item.
- A saved template preview is local to the controller and never overwrites an existing file.
- Post-failure recovery handles failed task results, but not unreachable hosts.
- One recovery decision applies to all failures from the same lockstep task.
- Ignoring a failure changes controller-side execution state and recap statistics; it does not undo remote changes.
- Interactive line editing depends on Python `readline` and a terminal stdin.
- Secret masking cannot detect every sensitive value.

## 19. Architecture and project files

The main implementation is `strategy_plugins/inspect_step.py`. It inherits `ansible.plugins.strategy.linear.StrategyModule` and integrates with the Ansible 2.12-2.13 step hook, lockstep task selection, pending-result processing, handler execution, task queueing, `VariableManager`, and `Templar`.

Architecture diagrams are stored as PlantUML source files in `diagramms/`:

- `architecture.puml` — components and dependencies;
- `task-lifecycle.puml` — task inspection and execution sequence;
- `variables.puml` — variable inspection and runtime update flow.

Files with the `-ru` suffix contain Russian versions of the same diagrams.

## 20. Runnable example

The `example/` directory contains a local two-host inventory, play variables, facts, role defaults and vars, nested and JSON values, `set_fact`, `register`, a host-specific template, a handler, host-specific loop items with `loop_control`, a condition, and an `inspect_demo` tagged breakpoint target.

Run it from the example directory:

```bash
cd example
ansible-playbook -i inventory playbook.yml --limit test --step
```

Useful commands for the first session:

```text
hosts
vars depth=1
v host_app_port host=test01
vars host_app_port host=test02
vars ansible_facts.python depth=1 host=test02
set host_app_port 9000
set host_app_port 9002 host=test02
eval {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf
eval {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf host=test02
eval-lookup {{ lookup('env', 'HOME') }} host=test02
eval-all {{ host_app_port }} diff=true
when all
loop all depth=2
result all depth=1
watch add {{ app_port }}
break tag inspect_demo
go
args
template test01
template test02
template-save /tmp/test02-application.conf test02
w
r
i
```

## 21. All-command examples and pattern reference

### Execution control

```text
r
run
r!
run!
s
skip
c
continue
g
go
```

At least one breakpoint must exist before using `g` or `go`. The `c` and `continue` commands do not use breakpoints and disable subsequent ordinary prompts.

### Task context and hosts

```text
w
hosts
h
help
?
```

### Variables with `vars`, `v`, and `var`

```text
vars app_port
v app_port
v app_config.workers
vars json_settings.limits.connections
v application_servers.0.address
v app_port host=test02
vars hostvars
v hostvars host=test02
vars hostvars.ansible_facts host=test02
vars glob=role_*
v glob=*port*
vars glob=role_?
v regex=^role_.*$
vars regex=^(role|app)_[a-z0-9_]+$
v regex=^backend_[0-9]+$
var app_password | length
var app_config.workers + host_app_port host=test02
```

`vars`, `v`, and `var` are fully equivalent. Glob and regexp patterns inspect top-level names only; use the `glob=` or `regex=` prefix. Use a dot path rather than a pattern to inspect nested values.

```text
vars
v
vars host=test02
vars depth=1
v depth=2 host=test02
vars app_config
v app_config depth=1
vars ansible_facts.python depth=2 host=test02
vars! app_config host=test02 depth=3
v! app_config host=test02 depth=3
```

The selector or expression may span multiple words. `host=HOST` and `depth=N` may appear in any order but each may be specified only once.

### Runtime variable changes

```text
set app_port 9000
set feature_enabled true
set deployment_mode blue
set app_port 9002 host=test02
set ports '[8080, 8081]'
set settings '{"workers": 4}'
set release_code '"0012"'
```

### Jinja expressions

```text
eval {{ app_port }}
e {{ app_port | int + 100 }}
eval {{ app_root }}/{{ app_name }}.conf
eval {{ app_config.workers }} host=test02
eval {{ 'on' if feature_enabled else 'off' }}
eval {{ [app_port, host_color] }}
eval-lookup {{ lookup('env', 'HOME') }}
eval-lookup {{ query('fileglob', '/etc/*.conf') }} host=test02
eval-lookup {{ lookup('hashi_vault', hashicorp_vault_hashi_vault_path_root + (hashicorp_vault_cacertfile | basename)) }} host=test01
eval-all {{ inventory_hostname }}
eval-all {{ host_app_port }} diff=true
eval-all {{ app_config }} diff=true
```

`eval-lookup` executes only for its default or explicitly selected host; there is no `all` form and it cannot be used by watches. `eval-all` uses only hosts active for the current task. `diff=true` collapses identical successful values into one output.

### Conditions and the previous result

```text
when
when test02
when all
result
result test02
result all
result all depth=1
result! test02 depth=3
```

### Loop preview

```text
loop
loop test02
loop all
loop all depth=1
loop depth=2 test02
loop! all depth=3
loop eval 2 {{ item }}:{{ ansible_loop.index }} host=test01
loop when 2 host=test01
loop args 2 host=test01
loop template 2 host=test01
```

Use `loop` for masked output and `loop!` only when the unmasked item values are intentionally required. Item-aware commands use a 1-based preview number and one host. They do not provide per-item execution control.

### Watches

```text
watch add {{ app_port }}
watch add {{ app_port }} host=test02
watch add {{ app_root }}/{{ app_name }}-{{ inventory_hostname }}.conf
watch list
watch delete 1
```

A watch without `host=HOST` uses the inspection host at each subsequent stop. Lookups are disabled, but the result is not masked.

### Breakpoints and regular expressions

```text
break task application
break task 'Exercise a loop'
break task '(?i)configure|restart'
break task '^test_role : Render'
break task 'condition$'
break role test_role
break tag inspect_demo
break list
break delete 1
g
```

Pattern comparison:

| Command | Syntax | Matching operation | Example |
|---|---|---|---|
| `vars`, `v`, `var` | `glob=` + pattern | complete top-level variable name | `v glob=*port*` |
| `vars`, `v`, `var` | `regex=` + Python regexp | complete top-level name through `fullmatch` | `vars regex=^app_.*$` |
| `break task` | Python regexp | substring search through `search` | `break task application` |
| `break role` | exact string | case-sensitive equality | `break role test_role` |
| `break tag` | exact string | case-sensitive equality | `break tag inspect_demo` |

Therefore, `break task *application*` is invalid, `break task .*application.*` is valid but redundant, and the recommended form is `break task application`.

### Task arguments and templates

```text
raw
a
args
args!
template
template test02
template-save /tmp/app.conf test02
template-save "/tmp/preview files/app.conf" test02
```

### Post-failure prompt

These commands are available only at `inspect-failure>`:

```text
i
ignore
c
continue
a
abort
h
help
?
```

The project changelog is available in [CHANGELOG.md](CHANGELOG.md).
