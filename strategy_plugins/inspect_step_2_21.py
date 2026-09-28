# -*- coding: utf-8 -*-
"""Provide an interactive task inspector for ansible-core 2.21.

RU: Реализует интерактивный inspector task поверх linear strategy ansible-core 2.21.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import fnmatch
import json
import os
import pprint
import re
import shlex
from collections.abc import Mapping

import yaml

try:
    import readline as _readline
except ImportError:
    _readline = None
else:
    if hasattr(_readline, 'set_auto_history'):
        _readline.set_auto_history(True)

from ansible import constants as C
from ansible.errors import AnsibleError
from ansible.executor.module_common import _apply_action_arg_defaults
from ansible.module_utils.common.text.converters import to_bytes, to_text
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.parsing.yaml.dumper import AnsibleDumper
from ansible.playbook.block import Block
from ansible.playbook.handler import Handler
from ansible.plugins.loader import lookup_loader
from ansible.plugins.strategy.linear import StrategyModule as LinearStrategy
from ansible.release import __version__ as ANSIBLE_VERSION
from ansible.template import Templar, trust_as_template
from ansible._internal._templating._template_vars import generate_ansible_template_vars
from unittest.mock import patch


DOCUMENTATION = r'''
    name: inspect_step_2_21
    short_description: Interactively inspect tasks before executing them
    description:
      - Extends the ansible-core 2.21 linear strategy and its step hook.
      - Allows task variables, expressions, and arguments to be inspected before queueing.
      - Explicitly evaluates trusted lookup expressions for one selected host.
      - Previews host-specific loop items and loop-control metadata without task execution.
      - Evaluates expressions, conditions, arguments, and templates for one loop item.
      - Previews built-in template results without writing the remote destination.
      - Executes dynamic include trees without intermediate task stops when requested.
      - Browses compiled and runtime-expanded tasks and selects exact task breakpoints.
      - Explicitly executes one selected task with task-level no_log disabled.
    author: Custom
    notes:
      - Technical compatibility is ansible-core 2.21.
      - The primary tested version is ansible-core 2.21.4.
      - Run ansible-playbook with C(--step) to enable the inspector.
'''


HIDDEN_VALUE = '*** HIDDEN ***'
PATH_UNDEFINED = object()
VERSION = '2.1.0'
PRIMARY_TESTED_ANSIBLE_VERSION = '2.21.4'
MINIMUM_ANSIBLE_VERSION = (2, 21)
MAXIMUM_ANSIBLE_VERSION = (2, 22)
_VERSION_DISPLAYED = False
TEMPLATE_ACTIONS = (
    'template',
    'ansible.builtin.template',
    'ansible.legacy.template',
)
SECRET_KEY_PARTS = (
    'password',
    'passwd',
    'secret',
    'token',
    'api_key',
    'apikey',
    'private_key',
)

HELP_TEXT = '''Commands:

  r | run              execute task
  r! | run!            execute task with task-level no_log disabled
  ra | run-all         execute a dynamic include completely, then resume stops
  s | skip             skip task
  c | continue         execute task and disable normal task stops
  g | go               execute tasks until a breakpoint matches

  w                     show current task source again

  hosts                 show play hosts selected by inventory and --limit
  vars | v | var [NAME|PATH|glob=PATTERN|regex=REGEXP|JINJA_EXPRESSION] [host=HOST] [depth=N]
                        show variables; secrets are masked by default
                        glob= and regex= search top-level names
  vars! | v! | var! [NAME|PATH|glob=PATTERN|regex=REGEXP|JINJA_EXPRESSION] [host=HOST] [depth=N]
                        same, including secrets
  set NAME YAML_VALUE [host=HOST]
                        change a variable for all play hosts, or one host
  e | eval JINJA_EXPRESSION [host=HOST]
                        evaluate an expression; Ansible lookups are disabled
  eval-lookup JINJA_EXPRESSION [host=HOST]
                        evaluate once with Ansible lookups enabled
  eval-all JINJA_EXPRESSION [diff=true]
                        evaluate an expression for every current task host
  when [HOST|all]      evaluate the current task's when conditions
  loop [HOST|all] [depth=N]
                        preview loop items with secrets masked
  loop! [HOST|all] [depth=N]
                        same, including secrets
  loop eval ITEM JINJA_EXPRESSION [host=HOST]
  loop when ITEM [host=HOST]
  loop args ITEM [host=HOST]
  loop template ITEM [host=HOST]
                        inspect one 1-based loop item without executing it
  result [HOST|all] [depth=N]
                        show the previous task result with secrets masked
  result! [HOST|all] [depth=N]
                        same, including secrets
  watch add EXPRESSION [host=HOST]
  watch list | watch delete ID
                        manage expressions shown at every interactive stop
  tasks [tree] [host=HOST] [regex=REGEXP] [role=NAME] [tag=TAG]
                        browse reachable tasks; dynamic children appear at runtime
  break task REGEX | break role NAME | break tag TAG
  break pick TASK_ID
  break list | break delete ID
                        manage breakpoints used by go

  a | args             show templated task arguments
  args!                show templated args without masking
  raw                  show original task.args
  template [HOST]      render template task and show resulting content
  template-save LOCAL_PATH [HOST]
                        render and save locally without overwriting a file

Task failure prompt:

  i | ignore           ignore failure and keep current step mode
  c | continue         ignore failure and disable normal task stops
  a | abort            keep the Ansible failure

  h | help | ?         show help'''

FAILURE_HELP_TEXT = '''Failure commands:

  i | ignore           ignore this task failure and keep current step mode
  c | continue         ignore this task failure and disable normal task stops
  a | abort            keep the Ansible failure for affected hosts

  h | help | ?         show failure help'''


def _key_contains_secret(key):
    key_text = to_text(key, errors='surrogate_or_strict').lower()
    return any(part in key_text for part in SECRET_KEY_PARTS)


def _container_summary(value):
    try:
        size = len(value)
    except (TypeError, AttributeError):
        size = '?'

    if isinstance(value, Mapping):
        return '<mapping: %s keys>' % size
    if isinstance(value, list):
        return '<list: %s items>' % size
    return '<tuple: %s items>' % size


def _normalize_value(value, mask_secrets=False, active_ids=None, max_depth=None, depth=0):
    """Build a printable nested copy without mutating Ansible variables.

    RU: Создаёт пригодную для вывода вложенную копию, не изменяя variables Ansible.

    Args / Параметры:
        value (object): Source value. / Исходное значение.
        mask_secrets (bool): Mask values under secret-like keys. / Маскировать секреты.
        active_ids (set or None): Container IDs in the active recursion path. /
            ID контейнеров в текущем пути рекурсии.
        max_depth (int or None): Maximum expanded container depth. / Глубина раскрытия.
        depth (int): Current recursion depth. / Текущая глубина рекурсии.

    Returns / Возвращает:
        object: Printable copy, depth summary, or recursive-reference marker. /
            Копию, сводку глубины или маркер рекурсивной ссылки.
    """
    if active_ids is None:
        active_ids = set()

    if isinstance(value, Mapping):
        if max_depth is not None and depth >= max_depth:
            return _container_summary(value)
        # EN: Track only the active path so repeated non-cyclic objects remain printable.
        # RU: Храним только активный путь, чтобы повторные нерекурсивные объекты выводились.
        value_id = id(value)
        if value_id in active_ids:
            return '<recursive reference>'
        active_ids.add(value_id)
        try:
            return {
                key: HIDDEN_VALUE
                if mask_secrets and _key_contains_secret(key)
                else _normalize_value(
                    item,
                    mask_secrets=mask_secrets,
                    active_ids=active_ids,
                    max_depth=max_depth,
                    depth=depth + 1,
                )
                for key, item in value.items()
            }
        finally:
            active_ids.remove(value_id)

    if isinstance(value, list):
        if max_depth is not None and depth >= max_depth:
            return _container_summary(value)
        value_id = id(value)
        if value_id in active_ids:
            return '<recursive reference>'
        active_ids.add(value_id)
        try:
            return [
                _normalize_value(
                    item,
                    mask_secrets=mask_secrets,
                    active_ids=active_ids,
                    max_depth=max_depth,
                    depth=depth + 1,
                )
                for item in value
            ]
        finally:
            active_ids.remove(value_id)

    if isinstance(value, tuple):
        if max_depth is not None and depth >= max_depth:
            return _container_summary(value)
        value_id = id(value)
        if value_id in active_ids:
            return '<recursive reference>'
        active_ids.add(value_id)
        try:
            return tuple(
                _normalize_value(
                    item,
                    mask_secrets=mask_secrets,
                    active_ids=active_ids,
                    max_depth=max_depth,
                    depth=depth + 1,
                )
                for item in value
            )
        finally:
            active_ids.remove(value_id)

    return value


def _mask_secrets(value, active_ids=None):
    """Return a recursively masked copy without modifying Ansible variables.

    RU: Возвращает рекурсивно маскированную копию без изменения variables Ansible.

    Args / Параметры:
        value (object): Value to copy and mask. / Значение для копирования и маскирования.
        active_ids (set or None): Active recursion path. / Активный путь рекурсии.

    Returns / Возвращает:
        object: Masked printable copy. / Маскированная копия для вывода.
    """
    return _normalize_value(value, mask_secrets=True, active_ids=active_ids)


def _parse_json_structure(value):
    """Parse JSON object or array strings while leaving other values unchanged.

    RU: Разбирает JSON object/array из строки, не изменяя остальные значения.

    Args / Параметры:
        value (object): Candidate value. / Проверяемое значение.

    Returns / Возвращает:
        object: Parsed dict/list or the original value when parsing is inapplicable or fails. /
            dict/list либо исходное значение, если parsing неприменим или завершился ошибкой.
    """
    if not isinstance(value, str):
        return value

    candidate = value.strip()
    if not candidate.startswith(('{', '[')):
        return value

    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


def _ansible_major_minor(version):
    """Extract the ansible-core major and minor version numbers.

    RU: Извлекает major и minor из версии ansible-core.

    Args / Параметры:
        version (object): Version convertible to text. / Версия, преобразуемая в строку.

    Returns / Возвращает:
        tuple or None: ``(major, minor)`` or ``None`` for an unknown format. /
            ``(major, minor)`` либо ``None`` для неизвестного формата.
    """
    match = re.match(r'^(\d+)\.(\d+)', to_text(version))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


class StrategyModule(LinearStrategy):
    """Add an interactive pre-task inspector to Ansible's linear strategy.

    RU: Добавляет интерактивный inspector перед task в linear strategy Ansible.

    The implementation relies on private step, result, and iterator APIs from
    ansible-core 2.21. / Реализация использует внутренние API step, result и
    iterator из ansible-core 2.21.
    """

    def __init__(self, tqm):
        """Initialize inspector state and enforce the supported Ansible version gate.

        RU: Инициализирует состояние inspector и проверяет совместимость версии Ansible.

        Args / Параметры:
            tqm (TaskQueueManager): Active Ansible task queue manager. /
                Активный менеджер очереди task Ansible.

        Returns / Возвращает:
            None: Initialization is performed in place. / Состояние создаётся in place.

        Raises / Исключения:
            AnsibleError: Installed ansible-core is outside the supported range.
        """
        super(StrategyModule, self).__init__(tqm)
        global _VERSION_DISPLAYED
        if not _VERSION_DISPLAYED:
            self._display.display('inspect_step version %s' % VERSION)
            self._check_ansible_version()
            _VERSION_DISPLAYED = True
        self._inspect_hosts_by_task = {}
        self._inspect_host_states = {}
        self._inspect_failure_actions = {}
        self._inspect_meta_decisions = {}
        self._inspect_failure_prompt_enabled = self._step
        self._inspect_task_var_refresh = set()
        self._inspect_last_result = None
        self._inspect_watches = []
        self._inspect_next_watch_id = 1
        self._inspect_breakpoints = []
        self._inspect_next_breakpoint_id = 1
        self._inspect_task_catalog = {}
        self._inspect_task_catalog_by_id = {}
        self._inspect_next_task_catalog_id = 1
        self._inspect_task_catalog_initialized = False
        self._inspect_task_catalog_play_name = None
        self._inspect_task_catalog_gather_facts = None
        self._inspect_no_log_overrides = {}
        self._inspect_go = False
        self._inspect_run_all_include = None
        self._inspect_run_all_flushing_handlers = False

    def _check_ansible_version(self):
        """Reject releases outside this standalone implementation's API range."""
        version = _ansible_major_minor(ANSIBLE_VERSION)
        if version is None or not MINIMUM_ANSIBLE_VERSION <= version < MAXIMUM_ANSIBLE_VERSION:
            raise AnsibleError(
                'This inspect_step variant requires ansible-core 2.21; detected %s.'
                % ANSIBLE_VERSION
            )
        self._display.display('Ansible compatibility: ansible-core %s (2.21)' % ANSIBLE_VERSION)

    def _get_next_task_lockstep(self, hosts, iterator):
        """Remember hosts and iterator states for the next lockstep task.

        RU: Сохраняет hosts и состояния iterator для следующей lockstep-task.

        Args / Параметры:
            hosts (list): Hosts eligible for the next task. / Hosts следующей task.
            iterator (PlayIterator): Active play iterator. / Активный iterator play.

        Returns / Возвращает:
            list: ``(host, task)`` pairs returned by the linear strategy. /
                Пары ``(host, task)`` из linear strategy.
        """
        # EN/RU: A no_log override belongs only to the previously selected lockstep task.
        self._inspect_no_log_overrides.clear()
        self._ensure_task_catalog(iterator)
        host_tasks = super(StrategyModule, self)._get_next_task_lockstep(hosts, iterator)
        if any(task is not None and not isinstance(task, Handler) for _, task in host_tasks):
            self._inspect_run_all_flushing_handlers = False
        hosts_by_task = {}
        for host, task in host_tasks:
            if task is not None:
                hosts_by_task.setdefault(task._uuid, []).append(host)
                self._record_task_catalog(task, host=host, runtime=True)
        self._inspect_hosts_by_task = hosts_by_task
        # EN: Result processing removes failed hosts; snapshots make explicit recovery possible.
        # RU: Result processing удаляет failed hosts; snapshots позволяют явно восстановить их.
        self._inspect_host_states = {
            (task._uuid, host.get_name()): iterator.get_host_state(host)
            for host, task in host_tasks
            if task is not None
        }
        self._inspect_failure_actions = {}
        self._inspect_meta_decisions = {}
        return host_tasks

    def _execute_meta(self, task, play_context, iterator, target_host):
        """Offer one lockstep decision before an explicit meta action.

        RU: Даёт одно lockstep-решение перед явной meta-action.

        Args / Параметры:
            task (Task): Meta task selected by the linear strategy. /
                Meta-task, выбранная linear strategy.
            play_context (PlayContext): Current execution context. / Контекст выполнения.
            iterator (PlayIterator): Active play iterator. / Активный iterator play.
            target_host (Host): Host selected to execute the meta action. /
                Host, выбранный для выполнения meta-action.

        Returns / Возвращает:
            list: Parent meta results, or an empty list when the operator skips the action. /
                Results родителя либо пустой list при пропуске action оператором.
        """
        if self._step and not task.implicit:
            decision = self._inspect_meta_decisions.get(task._uuid)
            if decision is None:
                decision = self._take_step(task)
                self._inspect_meta_decisions[task._uuid] = decision
            if not decision:
                return []

        run_all_flush = (
            self._inspect_run_all_include is not None
            and task.args.get('_raw_params') == 'flush_handlers'
            and self._is_within_include(
                task,
                self._inspect_run_all_include['uuid'],
            )
        )
        self._inspect_run_all_flushing_handlers = run_all_flush
        try:
            return super(StrategyModule, self)._execute_meta(
                self._task_with_no_log_override(
                    task,
                    host=target_host,
                    consume=True,
                ),
                play_context,
                iterator,
                target_host,
            )
        finally:
            self._inspect_run_all_flushing_handlers = run_all_flush

    def _is_dynamic_include(self, task):
        """Return whether a task is a runtime ``include_tasks`` or ``include_role``.

        RU: Проверяет, является ли task runtime-действием ``include_tasks`` или
        ``include_role``.

        Args / Параметры:
            task (Task): Candidate task. / Проверяемая task.

        Returns / Возвращает:
            bool: Whether the task is a supported dynamic include. /
                Является ли task поддерживаемым dynamic include.
        """
        return (
            task.action in C._ACTION_INCLUDE_TASKS
            or task.action in C._ACTION_INCLUDE_ROLE
        )

    def _is_within_include(self, task, include_uuid):
        """Return whether a task belongs to a selected dynamic include tree.

        RU: Проверяет принадлежность task выбранному дереву dynamic include.

        Args / Параметры:
            task (Task): Candidate descendant task. / Проверяемая task-потомок.
            include_uuid (str): UUID of the selected include. / UUID выбранного include.

        Returns / Возвращает:
            bool: Whether the parent chain contains the include. /
                Содержит ли parent chain выбранный include.
        """
        current = task
        visited = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if getattr(current, '_uuid', None) == include_uuid:
                return True
            current = getattr(current, '_parent', None)
        return False

    def _task_parent_includes(self, task):
        """Return parent include/import tasks from outermost to nearest."""
        include_actions = set(C._ACTION_ALL_INCLUDE_IMPORT_TASKS)
        include_actions.update(C._ACTION_ALL_PROPER_INCLUDE_IMPORT_ROLES)
        parents = []
        current = getattr(task, '_parent', None)
        visited = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if getattr(current, 'action', None) in include_actions:
                parents.append(current)
            current = getattr(current, '_parent', None)
        parents.reverse()
        return parents

    def _task_role_names(self, task):
        """Return both FQCN and short role names attached to a task."""
        role = getattr(task, '_role', None)
        if role is None:
            return set()
        names = set()
        for include_fqcn in (True, False):
            try:
                name = role.get_name(include_role_fqcn=include_fqcn)
            except TypeError:
                name = role.get_name()
            if name:
                names.add(to_text(name))
        return names

    def _record_task_catalog_entry(
        self,
        task,
        parent_uuid=None,
        host=None,
        runtime=False,
    ):
        """Add or refresh one real or synthetic task catalog entry."""
        task_uuid = getattr(task, '_uuid', None)
        if task_uuid is None or getattr(task, 'implicit', False):
            return None

        action = to_text(getattr(task, 'action', '') or '')
        if (
            action == 'gather_facts'
            and not runtime
            and self._inspect_task_catalog_gather_facts is False
        ):
            return None
        static_import = bool(getattr(task, 'statically_loaded', False)) or (
            action in C._ACTION_IMPORT_TASKS or action in C._ACTION_IMPORT_ROLE
        )
        dynamic_include = self._is_dynamic_include(task)
        entry = self._inspect_task_catalog.get(task_uuid)
        if entry is None:
            role_names = self._task_role_names(task)
            role_name = min(role_names, key=len) if role_names else None
            entry = {
                'id': self._inspect_next_task_catalog_id,
                'uuid': task_uuid,
                'name': to_text(task.get_name()),
                'action': action,
                'role': role_name,
                'role_names': role_names,
                'tags': set(to_text(tag) for tag in (getattr(task, 'tags', None) or [])),
                'path': to_text(task.get_path() or 'unknown source'),
                'parent_uuid': parent_uuid,
                'dynamic': dynamic_include,
                'static_import': static_import,
                'handler': hasattr(task, 'notified_hosts'),
                'selectable': not static_import,
                'runtime': bool(runtime),
                'seen_hosts': set(),
            }
            self._inspect_next_task_catalog_id += 1
            self._inspect_task_catalog[task_uuid] = entry
            self._inspect_task_catalog_by_id[entry['id']] = entry
        else:
            if entry['parent_uuid'] is None and parent_uuid is not None:
                entry['parent_uuid'] = parent_uuid
            entry['runtime'] = entry['runtime'] or bool(runtime)
            entry['handler'] = entry['handler'] or hasattr(task, 'notified_hosts')

        if host is not None:
            entry['seen_hosts'].add(host.get_name())
        return entry

    def _record_task_catalog(self, task, host=None, runtime=False):
        """Record a task and include/import context missing from the compiled list."""
        parent_uuid = None
        for parent in self._task_parent_includes(task):
            parent_entry = self._record_task_catalog_entry(
                parent,
                parent_uuid=parent_uuid,
                host=host,
                runtime=runtime,
            )
            if parent_entry is not None:
                parent_uuid = parent_entry['uuid']
        return self._record_task_catalog_entry(
            task,
            parent_uuid=parent_uuid,
            host=host,
            runtime=runtime,
        )

    def _walk_catalog_blocks(self, value):
        """Record tasks recursively from Ansible's compiled Block structures."""
        if isinstance(value, Block):
            for section in ('block', 'rescue', 'always'):
                self._walk_catalog_blocks(getattr(value, section, []))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                self._walk_catalog_blocks(item)
            return
        if getattr(value, 'action', None) is not None:
            self._record_task_catalog(value)

    def _ensure_task_catalog(self, iterator):
        """Preload statically known tasks once; runtime includes extend this catalog."""
        if self._inspect_task_catalog_initialized:
            return
        self._inspect_task_catalog_initialized = True
        play = getattr(iterator, '_play', None)
        if play is not None:
            self._inspect_task_catalog_gather_facts = getattr(play, 'gather_facts', None)
            try:
                self._inspect_task_catalog_play_name = to_text(play.get_name())
            except AttributeError:
                self._inspect_task_catalog_play_name = to_text(getattr(play, 'name', ''))
        self._walk_catalog_blocks(getattr(iterator, '_blocks', []))
        self._walk_catalog_blocks(getattr(play, 'handlers', []) if play is not None else [])

    def _parse_tasks_command(self, response):
        """Parse task-browser layout and filters."""
        try:
            parts = shlex.split(response)
        except ValueError as exc:
            raise ValueError('cannot parse command: %s' % to_text(exc))
        if not parts or parts[0].lower() != 'tasks':
            raise ValueError('tasks command is required')

        options = {'tree': False, 'host': None, 'regex': None, 'role': None, 'tag': None}
        for part in parts[1:]:
            if part.lower() == 'tree':
                if options['tree']:
                    raise ValueError('tree is specified more than once')
                options['tree'] = True
                continue
            if '=' not in part:
                raise ValueError("unknown option '%s'" % part)
            key, value = part.split('=', 1)
            key = key.lower()
            if key not in ('host', 'regex', 'role', 'tag'):
                raise ValueError("unknown option '%s'" % key)
            if options[key] is not None:
                raise ValueError("option '%s' is specified more than once" % key)
            if not value:
                raise ValueError("option '%s' must not be empty" % key)
            options[key] = value
        if options['regex'] is not None:
            try:
                options['compiled_regex'] = re.compile(options['regex'])
            except re.error as exc:
                raise ValueError('invalid task regexp: %s' % to_text(exc))
        else:
            options['compiled_regex'] = None
        return options

    def _task_catalog_matches(self, entry, options):
        """Return whether one catalog entry passes all requested filters."""
        if (
            options['compiled_regex'] is not None
            and options['compiled_regex'].search(entry['name']) is None
        ):
            return False
        if options['role'] is not None and options['role'] not in entry['role_names']:
            return False
        if options['tag'] is not None and options['tag'] not in entry['tags']:
            return False
        return True

    def _task_catalog_status(self, entry, current_uuid, host_name):
        if entry['uuid'] == current_uuid:
            return 'CURRENT'
        if host_name is None:
            return 'REACHED' if entry['seen_hosts'] else 'PENDING'
        return 'REACHED' if host_name in entry['seen_hosts'] else 'PENDING'

    def _task_catalog_markers(self, entry, has_children):
        markers = ['action=%s' % entry['action']]
        if entry['dynamic']:
            markers.append('dynamic')
            if not has_children:
                markers.append('not expanded')
        if entry['static_import']:
            markers.extend(('static import', 'group only'))
        if entry['handler']:
            markers.append('handler')
        if entry['role']:
            markers.append('role=%s' % entry['role'])
        if entry['tags']:
            markers.append('tags=%s' % ','.join(sorted(entry['tags'])))
        return '; '.join(markers)

    def _show_task_catalog(self, task, inspect_host, options):
        """Display a flat or include-aware view of reachable tasks."""
        selected_host = self._resolve_inspection_host(options['host'], inspect_host)
        if options['host'] is not None and selected_host is None:
            return
        host_name = selected_host.get_name() if selected_host is not None else None
        entries = sorted(self._inspect_task_catalog.values(), key=lambda item: item['id'])
        matched = [entry for entry in entries if self._task_catalog_matches(entry, options)]
        if not matched:
            self._display.display('No tasks match the selected filters')
            return

        current_uuid = getattr(task, '_uuid', None)
        current_host_names = set(
            current_host.get_name()
            for current_host in self._inspect_hosts_by_task.get(current_uuid, [])
        )
        if host_name is not None and host_name not in current_host_names:
            current_uuid = None
        host_label = host_name or '<all hosts>'
        self._display.display(
            '\nTASKS [%s; %d matched]' % (host_label, len(matched))
        )
        self._display.display(
            'PLAY: %s' % (self._inspect_task_catalog_play_name or '<unknown>')
        )

        children = {}
        for entry in entries:
            children.setdefault(entry['parent_uuid'], []).append(entry)

        if not options['tree']:
            for entry in matched:
                marker = self._task_catalog_markers(
                    entry,
                    bool(children.get(entry['uuid'])),
                )
                self._display.display(
                    '  [%03d] %-7s %s | %s | %s'
                    % (
                        entry['id'],
                        self._task_catalog_status(entry, current_uuid, host_name),
                        entry['name'],
                        marker,
                        entry['path'],
                    )
                )
            return

        visible_uuids = set(entry['uuid'] for entry in matched)
        by_uuid = dict((entry['uuid'], entry) for entry in entries)
        for entry in matched:
            parent_uuid = entry['parent_uuid']
            while parent_uuid in by_uuid:
                visible_uuids.add(parent_uuid)
                parent_uuid = by_uuid[parent_uuid]['parent_uuid']

        def display_entry(entry, depth):
            visible_children = [
                child
                for child in children.get(entry['uuid'], [])
                if child['uuid'] in visible_uuids
            ]
            marker = self._task_catalog_markers(
                entry,
                bool(children.get(entry['uuid'])),
            )
            self._display.display(
                '%s[%03d] %-7s %s | %s | %s'
                % (
                    '  ' * depth,
                    entry['id'],
                    self._task_catalog_status(entry, current_uuid, host_name),
                    entry['name'],
                    marker,
                    entry['path'],
                )
            )
            for child in visible_children:
                display_entry(child, depth + 1)

        active_role = None
        for entry in children.get(None, []):
            if entry['uuid'] not in visible_uuids:
                continue
            if entry['role'] != active_role:
                active_role = entry['role']
                if active_role:
                    self._display.display('  ROLE: %s' % active_role)
            display_entry(entry, 1 if active_role else 0)

    def _task_with_no_log_override(self, task, host=None, consume=False):
        """Return a task copy with task-level ``no_log`` disabled when requested."""
        override_hosts = self._inspect_no_log_overrides.get(task._uuid)
        if override_hosts is None:
            return task
        task_copy = task.copy(exclude_parent=True, exclude_tasks=True)
        task_copy._parent = task._parent
        task_copy.no_log = False
        if consume and host is not None:
            override_hosts.discard(host.get_name())
            if not override_hosts:
                self._inspect_no_log_overrides.pop(task._uuid, None)
        return task_copy

    def _queue_task(self, host, task, task_vars, play_context):
        """Queue a task with inspector variable and ``no_log`` overrides.

        RU: Ставит task в очередь с изменениями variables и ``no_log`` из inspector.

        Args / Параметры:
            host (Host): Managed host. / Управляемый host.
            task (Task): Task being queued. / Task для постановки в очередь.
            task_vars (dict): Variables prepared by Ansible. / Variables от Ansible.
            play_context (PlayContext): Current execution context. / Контекст выполнения.

        Returns / Возвращает:
            object: Result from the parent linear strategy. / Результат linear strategy.
        """
        refresh_key = (task._uuid, host.get_name())
        if refresh_key in self._inspect_task_var_refresh:
            task_vars = self._get_task_vars(task, host)
            self._inspect_task_var_refresh.discard(refresh_key)
        task = self._task_with_no_log_override(task, host=host, consume=True)
        return super(StrategyModule, self)._queue_task(host, task, task_vars, play_context)

    def _prompt_after_failure(self, task, failed_host):
        """Ask how to handle an unignored failure for the current lockstep task.

        RU: Запрашивает действие после необработанной ошибки текущей lockstep-task.

        Args / Параметры:
            task (Task): Failed task. / Failed task.
            failed_host (Host): Host that produced the first handled failure. /
                Host, вернувший первую обрабатываемую ошибку.

        Returns / Возвращает:
            str: ``ignore``, ``continue``, or ``abort``; EOF maps to ``abort``. /
                ``ignore``, ``continue`` или ``abort``; EOF означает ``abort``.
        """
        active_hosts = self._inspect_hosts_by_task.get(task._uuid, [])
        self._display.display('\nINSPECT FAILURE: %s' % task.get_name())
        self._display.display('Failed host: %s' % failed_host.get_name())
        if len(active_hosts) > 1:
            self._display.display(
                'The decision applies to failures from this task on %d active hosts.'
                % len(active_hosts)
            )
        self._display.display(FAILURE_HELP_TEXT)

        while True:
            try:
                response = self._display.prompt('\ninspect-failure> ').strip().lower()
            except EOFError:
                self._display.warning('End of input; keeping the Ansible failure')
                return 'abort'

            if response in ('i', 'ignore'):
                return 'ignore'
            if response in ('c', 'continue'):
                self._step = False
                return 'continue'
            if response in ('a', 'abort'):
                self._display.display(
                    'ABORT AFTER FAILURE: keeping the Ansible failure for affected hosts'
                )
                return 'abort'
            if response in ('h', 'help', '?'):
                self._display.display(FAILURE_HELP_TEXT)
                continue
            if response:
                self._display.display(
                    "Unknown failure command '%s'. Type 'help' for commands." % response
                )

    def _restore_failed_host(self, iterator, task_result, host, count_as_ignored=True):
        """Restore a failed host to its pre-task iterator state and adjust recap data.

        RU: Восстанавливает failed host в состояние до task и корректирует recap.

        Args / Параметры:
            iterator (PlayIterator): Iterator whose host state was changed. /
                Iterator с изменённым состоянием host.
            task_result (TaskResult): Failed result being ignored. / Игнорируемый result.
            host (Host): Host to restore. / Восстанавливаемый host.
            count_as_ignored (bool): Update ignored/ok recap counters. /
                Обновить счётчики ignored/ok.

        Returns / Возвращает:
            bool: ``True`` when restored, ``False`` when no snapshot exists. /
                ``True`` при восстановлении, иначе ``False``.
        """
        task = task_result.task
        host_name = host.get_name()
        saved_state = self._inspect_host_states.get((task._uuid, host_name))
        if saved_state is None:
            self._display.warning(
                'Cannot continue %s after failure: iterator state is unavailable' % host_name
            )
            return False

        # EN: These are private Ansible states; this is why the version gate is strict.
        # RU: Это внутренние состояния Ansible, поэтому version gate намеренно строгий.
        iterator.set_state_for_host(host_name, saved_state.copy())
        while host_name in iterator._play._removed_hosts:
            iterator._play._removed_hosts.remove(host_name)
        self._tqm._failed_hosts.pop(host_name, None)

        if count_as_ignored:
            self._tqm._stats.decrement('failures', host_name)
            self._tqm._stats.increment('ok', host_name)
            self._tqm._stats.increment('ignored', host_name)
            if task_result.utr.changed:
                self._tqm._stats.increment('changed', host_name)

        self._display.display('CONTINUE HOST: %s (task failure ignored)' % host_name)
        return True

    def _process_pending_results(self, iterator, one_pass=False, max_passes=None):
        """Process worker results and apply the selected failure-recovery action.

        RU: Обрабатывает worker results и применяет выбранное восстановление после failure.

        Args / Параметры:
            iterator (PlayIterator): Active play iterator. / Активный iterator play.
            one_pass (bool): Request one parent processing pass. / Один проход обработки.
            max_passes (int or None): Parent pass limit. / Лимит проходов parent strategy.

        Returns / Возвращает:
            list: Task results returned by the parent strategy. /
                Results task, возвращённые parent strategy.
        """
        results = super(StrategyModule, self)._process_pending_results(
            iterator,
            one_pass=one_pass,
            max_passes=max_passes,
        )
        if self._inspect_failure_prompt_enabled:
            for task_result in results:
                task = task_result.task
                host = task_result.host
                if not task_result.utr.failed or task_result.utr.ignore_errors or not iterator.is_failed(host):
                    continue

                # EN: One operator decision applies to every failed host in this task batch.
                # RU: Одно решение оператора применяется ко всем failed hosts этой task.
                action = self._inspect_failure_actions.get(task._uuid)
                if action is None:
                    action = self._prompt_after_failure(task, host)
                    self._inspect_failure_actions[task._uuid] = action

                if action not in ('ignore', 'continue'):
                    continue

                self._restore_failed_host(iterator, task_result, host)
                if task.run_once is True:
                    for active_host in self._inspect_hosts_by_task.get(task._uuid, []):
                        if active_host.get_name() != host.get_name():
                            self._restore_failed_host(
                                iterator,
                                task_result,
                                active_host,
                                count_as_ignored=False,
                            )

        self._record_task_results(results)

        return results

    def _hosts_for_task(self, task, host=None):
        """Resolve the host batch controlled by one inspector prompt.

        RU: Определяет группу hosts, управляемую одним prompt inspector.

        Args / Параметры:
            task (Task): Current task. / Текущая task.
            host (Host or str or None): Optional forced host. / Необязательный явный host.

        Returns / Возвращает:
            list: Active Host objects, possibly empty. / Активные Host objects или пустой list.
        """
        if host is not None:
            if hasattr(host, 'get_name'):
                return [host]
            inventory_host = self._inventory.get_host(to_text(host))
            return [inventory_host] if inventory_host is not None else []

        hosts = self._inspect_hosts_by_task.get(task._uuid, [])
        if hosts:
            return hosts

        play = task.play
        if play is None:
            return []
        return [
            self._inventory.get_host(host_name)
            for host_name in self.get_hosts_remaining(play)
            if self._inventory.get_host(host_name) is not None
        ]

    def _get_task_vars(self, task, host):
        """Collect the effective task variables for one host.

        RU: Собирает effective variables task для одного host.

        Args / Параметры:
            task (Task): Task that defines variable context. / Task, задающая контекст.
            host (Host): Host whose variables are requested. / Host для получения variables.

        Returns / Возвращает:
            dict: Variables with TaskQueueManager magic values added. /
                Variables с magic values TaskQueueManager.

        Raises / Исключения:
            AnsibleError: The task is not attached to a play. / Task не связана с play.
        """
        play = task.play
        if play is None:
            raise AnsibleError('Cannot determine the play for this task')

        task_vars = self._variable_manager.get_vars(
            play=play,
            host=host,
            task=task,
            _hosts=self._hosts_cache,
            _hosts_all=self._hosts_cache_all,
        )
        self.add_tqm_variables(task_vars, play=play)
        return task_vars

    def _display_value(self, value, mask_secrets=False, json_format=False, max_depth=None):
        """Normalize, optionally mask, and pretty-print a diagnostic value.

        RU: Нормализует, при необходимости маскирует и форматирует значение диагностики.

        Args / Параметры:
            value (object): Value to display. / Выводимое значение.
            mask_secrets (bool): Enable heuristic secret masking. / Включить masking.
            json_format (bool): Prefer indented JSON for dict/list values. /
                Предпочитать форматированный JSON для dict/list.
            max_depth (int or None): Maximum expanded container depth. / Глубина вывода.

        Returns / Возвращает:
            None: Errors are reported as warnings instead of propagating. /
                Ошибки выводятся как warnings и не пробрасываются.
        """
        try:
            value = _parse_json_structure(value)
            value = _normalize_value(
                value,
                mask_secrets=mask_secrets,
                max_depth=max_depth,
            )
        except Exception as exc:
            self._display.warning('Cannot prepare value for display: %s' % to_text(exc))
            return
        rendered = None
        if json_format and isinstance(value, (dict, list)):
            try:
                rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            except (TypeError, ValueError):
                pass
        if rendered is None:
            try:
                rendered = pprint.pformat(value, width=100, sort_dicts=True)
            except Exception as exc:
                self._display.warning('Cannot pretty-print value: %s' % to_text(exc))
                rendered = to_text(value, errors='surrogate_then_replace')
        self._display.display(rendered)

    def _result_status(self, task_result):
        if task_result.utr.unreachable:
            return 'unreachable'
        if task_result.utr.failed:
            task = task_result.task
            recovery = self._inspect_failure_actions.get(task._uuid)
            if task_result.utr.ignore_errors or recovery in ('ignore', 'continue'):
                return 'ignored'
            return 'failed'
        if task_result.utr.skipped:
            return 'skipped'
        if task_result.utr.changed:
            return 'changed'
        return 'ok'

    def _record_task_results(self, results):
        for task_result in results:
            task = task_result.task
            if (
                self._inspect_last_result is None
                or self._inspect_last_result['task_uuid'] != task._uuid
            ):
                self._inspect_last_result = {
                    'task_uuid': task._uuid,
                    'task_name': task.get_name(),
                    'hosts': {},
                }

            raw_result = task_result.utr.as_result_dict()
            if isinstance(raw_result, Mapping):
                visible_result = {
                    key: value
                    for key, value in raw_result.items()
                    if not to_text(key).startswith('_ansible_')
                }
            else:
                visible_result = raw_result
            self._inspect_last_result['hosts'][task_result.host.get_name()] = {
                'status': self._result_status(task_result),
                'value': visible_result,
            }

    def _parse_host_depth_options(self, arguments):
        target = None
        max_depth = None
        for argument in arguments:
            if argument.startswith('depth='):
                if max_depth is not None:
                    raise ValueError('depth may be specified only once')
                try:
                    max_depth = int(argument.split('=', 1)[1])
                except ValueError:
                    raise ValueError('depth must be a positive integer')
                if max_depth < 1:
                    raise ValueError('depth must be a positive integer')
            elif target is None:
                target = argument
            else:
                raise ValueError('host or all may be specified only once')
        if target is not None and target != 'all' and target not in self._hosts_cache:
            raise ValueError("host '%s' is not active in the current play" % target)
        return target, max_depth

    def _show_last_result(self, target, inspect_host, reveal_secrets=False, max_depth=None):
        """Display the previous task result for one host or all recorded hosts.

        RU: Показывает result предыдущей task для одного или всех сохранённых hosts.

        Args / Параметры:
            target (str or None): Host name, ``all``, or default host. / Host, ``all`` или default.
            inspect_host (Host or None): Default inspection host. / Default host inspector.
            reveal_secrets (bool): Disable heuristic masking. / Отключить masking secrets.
            max_depth (int or None): Maximum result depth. / Глубина вывода result.

        Returns / Возвращает:
            None: Missing results are reported in output. / Отсутствующий result отмечается.
        """
        if self._inspect_last_result is None:
            self._display.display('No previous task result is available')
            return
        if reveal_secrets:
            self._display.warning('secret masking disabled')

        result_hosts = self._inspect_last_result['hosts']
        if target == 'all':
            host_names = [
                host_name for host_name in self._hosts_cache if host_name in result_hosts
            ]
            host_names.extend(
                sorted(host_name for host_name in result_hosts if host_name not in host_names)
            )
        else:
            default_name = inspect_host.get_name() if inspect_host is not None else None
            host_names = [target or default_name]

        self._display.display(
            'LAST RESULT: %s' % self._inspect_last_result['task_name']
        )
        for host_name in host_names:
            if host_name is None or host_name not in result_hosts:
                self._display.display(
                    'RESULT [%s]: unavailable for the previous task'
                    % (host_name or 'no inspection host')
                )
                continue
            host_result = result_hosts[host_name]
            self._display.display(
                'RESULT [%s] status=%s' % (host_name, host_result['status'])
            )
            self._display_value(
                host_result['value'],
                mask_secrets=not reveal_secrets,
                json_format=True,
                max_depth=max_depth,
            )

    def _variable_names_matching(self, pattern, task_vars, use_regex=False):
        """Return top-level variable names matching one glob or explicit regexp.

        RU: Возвращает top-level variables, совпавшие с glob или явным regexp.
        """
        expression = None
        if use_regex:
            try:
                expression = re.compile(pattern)
            except re.error as exc:
                raise ValueError('invalid variable regexp: %s' % to_text(exc))

        matches = []
        for variable_name in task_vars:
            variable_text = to_text(variable_name, errors='surrogate_or_strict')
            if (
                expression.fullmatch(variable_text)
                if use_regex
                else fnmatch.fnmatchcase(variable_text, pattern)
            ):
                matches.append(variable_name)
        return sorted(matches, key=to_text)

    def _resolve_variable_path(self, variable_path, task_vars, host=None):
        """Resolve a dotted mapping/list path, optionally inside one hostvars entry.

        RU: Разрешает dotted path по mapping/list, при необходимости внутри hostvars host.

        Args / Параметры:
            variable_path (str): Dotted variable path. / Dotted path variable.
            task_vars (Mapping): Root task-variable mapping. / Корневые variables task.
            host (Host or None): Host used to narrow ``hostvars``. / Host для ``hostvars``.

        Returns / Возвращает:
            tuple: ``(root_found, value)``; missing descendants use ``PATH_UNDEFINED``. /
                ``(root_found, value)``; отсутствующий path даёт ``PATH_UNDEFINED``.
        """
        path_parts = variable_path.split('.')
        root_name = path_parts.pop(0)
        if root_name not in task_vars:
            return False, PATH_UNDEFINED

        value = task_vars[root_name]
        if root_name == 'hostvars' and host is not None:
            host_name = host.get_name()
            if not path_parts or path_parts[0] != host_name:
                try:
                    value = value[host_name]
                except (KeyError, TypeError):
                    return True, PATH_UNDEFINED

        for path_part in path_parts:
            value = _parse_json_structure(value)
            if isinstance(value, Mapping):
                if path_part not in value:
                    return True, PATH_UNDEFINED
                value = value[path_part]
            elif isinstance(value, (list, tuple)) and path_part.isdigit():
                index = int(path_part)
                if index >= len(value):
                    return True, PATH_UNDEFINED
                value = value[index]
            else:
                return True, PATH_UNDEFINED

        return True, value

    def _show_vars(
        self,
        host,
        task_vars,
        variable_selector=None,
        reveal_secrets=False,
        max_depth=None,
        explicit_host=False,
    ):
        """Display a variable tree, selector match, or nested path with safe defaults.

        RU: Показывает variables, совпадения selector или nested path безопасно.

        Args / Параметры:
            host (Host): Host providing the variable context. / Host контекста variables.
            task_vars (dict or None): Effective variables. / Effective variables.
            variable_selector (str or None): Optional name, path, explicit glob, regexp, or expression. /
                Необязательные имя, path, явный glob, regexp или expression.
            reveal_secrets (bool): Disable heuristic masking. / Отключить masking secrets.
            max_depth (int or None): Maximum expanded depth. / Глубина раскрытия.
            explicit_host (bool): Narrow ``hostvars`` to ``host``. / Ограничить ``hostvars``.

        Returns / Возвращает:
            None: Resolution errors are printed in the current prompt. /
                Ошибки resolution выводятся в текущем prompt.
        """
        if task_vars is None:
            self._display.warning('Task variables are unavailable')
            return
        if reveal_secrets:
            self._display.warning('secret masking disabled')

        depth_suffix = ' depth=%d' % max_depth if max_depth is not None else ''
        value = task_vars
        json_format = False
        if variable_selector is not None:
            use_regex = variable_selector.startswith('regex=')
            use_glob = variable_selector.startswith('glob=')
            use_expression = not (
                use_regex
                or use_glob
                or re.fullmatch(
                    r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*',
                    variable_selector,
                ) is not None
            )
            if use_expression:
                expression = variable_selector
                if not expression.startswith('{{'):
                    expression = '{{ %s }}' % expression
                ok, value = self._evaluate_expression(expression, task_vars)
                if not ok:
                    self._display.warning(
                        'Cannot evaluate variable expression for %s: %s'
                        % (host.get_name(), value)
                    )
                    return
                self._display.display(
                    '%s [%s]%s ='
                    % (variable_selector, host.get_name(), depth_suffix)
                )
                self._display_value(
                    value,
                    mask_secrets=not reveal_secrets,
                    json_format=True,
                    max_depth=max_depth,
                )
                return
            pattern = (
                variable_selector.split('=', 1)[1]
                if use_regex or use_glob else variable_selector
            )
            if use_regex or use_glob:
                if not pattern:
                    pattern_type = 'regexp' if use_regex else 'glob'
                    self._display.display(
                        'Invalid variable %s: pattern is empty' % pattern_type
                    )
                    return
                try:
                    matching_names = self._variable_names_matching(
                        pattern,
                        task_vars,
                        use_regex=use_regex,
                    )
                except ValueError as exc:
                    self._display.display(to_text(exc).capitalize())
                    return
                if not matching_names:
                    pattern_type = 'regexp' if use_regex else 'glob'
                    self._display.display(
                        "No variables match %s '%s'" % (pattern_type, pattern)
                    )
                    return
                value = {name: task_vars[name] for name in matching_names}
                self._display.display(
                    'VARIABLES MATCHING %s [%s] [%s]%s'
                    % (
                        'REGEXP' if use_regex else 'GLOB',
                        pattern,
                        host.get_name(),
                        depth_suffix,
                    )
                )
            else:
                path_root_found, value = self._resolve_variable_path(
                    variable_selector,
                    task_vars,
                    host=host if explicit_host else None,
                )
                if not path_root_found or value is PATH_UNDEFINED:
                    label = 'Variable path' if '.' in variable_selector else 'Variable'
                    self._display.display(
                        "%s '%s' is undefined" % (label, variable_selector)
                    )
                    return
                if not reveal_secrets and any(
                    _key_contains_secret(path_part)
                    for path_part in variable_selector.split('.')
                ):
                    value = HIDDEN_VALUE
                self._display.display(
                    '%s [%s]%s ='
                    % (variable_selector, host.get_name(), depth_suffix)
                )
            json_format = True
        else:
            self._display.display('VARIABLES [%s]%s\n' % (host.get_name(), depth_suffix))

        self._display_value(
            value,
            mask_secrets=not reveal_secrets,
            json_format=json_format,
            max_depth=max_depth,
        )

    def _parse_vars_options(self, arguments):
        """Parse shared ``vars``/``v``/``var`` selector, host, and depth options.

        RU: Разбирает общие параметры selector, host и depth для ``vars``/``v``/``var``.

        Args / Параметры:
            arguments (list[str]): Command arguments. / Аргументы команды.

        Returns / Возвращает:
            tuple: ``(selector, host_name, max_depth)``. / Разобранные параметры.

        Raises / Исключения:
            ValueError: An option is empty, duplicated, or invalid. /
                Параметр пуст, повторён или некорректен.
        """
        selector_parts = []
        host_name = None
        max_depth = None

        for argument in arguments:
            if argument.startswith('depth='):
                if max_depth is not None:
                    raise ValueError('depth may be specified only once')
                try:
                    max_depth = int(argument.split('=', 1)[1])
                except ValueError:
                    raise ValueError('depth must be a positive integer')
                if max_depth < 1:
                    raise ValueError('depth must be a positive integer')
            elif argument.startswith('host='):
                if host_name is not None:
                    raise ValueError('host may be specified only once')
                host_name = argument.split('=', 1)[1]
                if not host_name:
                    raise ValueError('host name must not be empty')
            elif argument:
                selector_parts.append(argument)
            else:
                raise ValueError('variable selector must not be empty')

        return ' '.join(selector_parts) if selector_parts else None, host_name, max_depth

    def _parse_set_command(self, response):
        """Parse ``set NAME YAML_VALUE [host=HOST]`` into a typed value.

        RU: Разбирает ``set NAME YAML_VALUE [host=HOST]`` в typed value.

        Args / Параметры:
            response (str): Complete command line. / Полная строка команды.

        Returns / Возвращает:
            tuple: ``(variable_name, parsed_value, host_name)``. /
                ``(variable_name, parsed_value, host_name)``.

        Raises / Исключения:
            ValueError: Quoting, name, host, or YAML/JSON value is invalid. /
                Неверны quoting, имя, host или YAML/JSON value.
        """
        try:
            parts = shlex.split(response)
        except ValueError as exc:
            raise ValueError('cannot parse value: %s' % to_text(exc))

        host_name = None
        if parts and parts[-1].startswith('host='):
            host_name = parts.pop().split('=', 1)[1]
            if not host_name:
                raise ValueError('host name must not be empty')

        if len(parts) < 3:
            raise ValueError('variable name and value are required')

        variable_name = parts[1]
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', variable_name) is None:
            raise ValueError("invalid variable name '%s'" % variable_name)

        raw_value = ' '.join(parts[2:])
        try:
            value = yaml.safe_load(raw_value)
        except yaml.YAMLError as exc:
            raise ValueError('invalid YAML/JSON value: %s' % to_text(exc))

        return variable_name, value, host_name

    def _parse_eval_command(self, response):
        """Parse an expression command with an optional trailing host selector.

        RU: Разбирает expression-команду с optional trailing host selector.

        Args / Параметры:
            response (str): Complete ``eval`` or ``eval-lookup`` command. / Полная команда.

        Returns / Возвращает:
            tuple: ``(expression, host_name)``. / ``(expression, host_name)``.

        Raises / Исключения:
            ValueError: Expression is missing. / Expression отсутствует.
        """
        command_match = re.match(r'^\S+\s+(.+)$', response)
        if command_match is None:
            raise ValueError('Jinja expression is required')

        expression = command_match.group(1).strip()
        host_name = None
        # EN: Only a trailing host= token is syntax; embedded text remains Jinja input.
        # RU: Syntax является только trailing host=; embedded text остаётся частью Jinja.
        host_match = re.search(r'(?:^|\s)host=([^\s]+)\s*$', expression)
        if host_match is not None:
            host_name = host_match.group(1)
            expression = expression[:host_match.start()].rstrip()

        if not expression:
            raise ValueError('Jinja expression is required')
        return expression, host_name

    def _parse_eval_all_command(self, response):
        """Parse ``eval-all`` and its optional trailing ``diff=true|false`` flag.

        RU: Разбирает ``eval-all`` и optional trailing flag ``diff=true|false``.

        Args / Параметры:
            response (str): Complete command line. / Полная строка команды.

        Returns / Возвращает:
            tuple: ``(expression, show_diff)``. / ``(expression, show_diff)``.

        Raises / Исключения:
            ValueError: Expression is missing or diff is not boolean. /
                Нет expression либо diff не является boolean.
        """
        command_match = re.match(r'^\S+\s+(.+)$', response)
        if command_match is None:
            raise ValueError('Jinja expression is required')

        expression = command_match.group(1).strip()
        show_diff = False
        diff_match = re.search(r'(?:^|\s)diff=([^\s]+)\s*$', expression)
        if diff_match is not None:
            diff_value = diff_match.group(1).lower()
            if diff_value not in ('true', 'false'):
                raise ValueError('diff must be true or false')
            show_diff = diff_value == 'true'
            expression = expression[:diff_match.start()].rstrip()

        if not expression:
            raise ValueError('Jinja expression is required')
        return expression, show_diff

    def _evaluate_expression(self, expression, task_vars, disable_lookups=True):
        """Evaluate one Jinja expression in an effective host variable context.

        RU: Вычисляет Jinja-expression в effective контексте variables выбранного host.

        Args / Параметры:
            expression (str): Jinja text to evaluate. / Вычисляемый Jinja-текст.
            task_vars (dict or None): Variables exposed to Templar. / Variables для Templar.
            disable_lookups (bool): Block Ansible lookup plugins when true. /
                Блокировать lookup plugins Ansible.

        Returns / Возвращает:
            tuple: ``(True, value)`` or ``(False, error_text)``. /
                ``(True, value)`` либо ``(False, текст_ошибки)``.
        """
        if task_vars is None:
            return False, 'task variables are unavailable'
        try:
            templar = Templar(loader=self._loader, variables=task_vars)
            if disable_lookups:
                with patch.object(lookup_loader, 'get', side_effect=AnsibleError(
                    'Lookups are disabled for this inspection command; use eval-lookup.'
                )):
                    value = templar.template(trust_as_template(expression))
            else:
                value = templar.template(trust_as_template(expression))
        except Exception as exc:
            return False, to_text(exc)
        return True, _parse_json_structure(value)

    def _values_equal(self, values):
        if not values:
            return True
        try:
            normalized = [
                pprint.pformat(_normalize_value(value), width=100, sort_dicts=True)
                for value in values
            ]
        except Exception:
            normalized = [to_text(value, errors='surrogate_then_replace') for value in values]
        return len(set(normalized)) == 1

    def _show_expression_all(self, expression, hosts, task, task_vars_by_host, show_diff=False):
        """Evaluate one lookup-disabled expression across all current task hosts.

        RU: Вычисляет expression с отключёнными lookups для всех hosts текущей task.

        Args / Параметры:
            expression (str): Jinja expression. / Jinja-expression.
            hosts (list): Active task hosts. / Активные hosts task.
            task (Task): Current task. / Текущая task.
            task_vars_by_host (dict): Per-prompt variable cache. / Cache variables prompt.
            show_diff (bool): Collapse identical results or mark differences. /
                Свернуть одинаковые results либо отметить различия.

        Returns / Возвращает:
            None: Per-host errors are displayed without aborting evaluation. /
                Ошибки hosts выводятся без остановки вычисления.
        """
        if not hosts:
            self._display.warning('No active hosts for the current task')
            return

        evaluations = []
        for host in hosts:
            task_vars = self._vars_for_inspection_host(task, host, task_vars_by_host)
            ok, value = self._evaluate_expression(expression, task_vars)
            evaluations.append((host, ok, value))

        successful_values = [value for _host, ok, value in evaluations if ok]
        no_differences = (
            all(ok for _host, ok, _value in evaluations)
            and self._values_equal(successful_values)
        )
        if show_diff and no_differences:
            self._display.display(
                'EVAL-ALL: no differences across %d hosts' % len(evaluations)
            )
            self._display_value(successful_values[0], json_format=True)
            return

        if show_diff:
            self._display.display('EVAL-ALL: host values differ')
        for host, ok, value in evaluations:
            if not ok:
                self._display.warning(
                    'Cannot evaluate expression for %s: %s'
                    % (host.get_name(), value)
                )
                continue
            self._display.display('EVAL [%s] =' % host.get_name())
            if isinstance(value, str):
                self._display.display(to_text(value, errors='surrogate_then_replace'))
            else:
                self._display_value(value, json_format=True)

    def _set_variable(self, task, variable_name, value, host_name, task_vars_by_host):
        """Set a non-persistent fact for one host or every host in the play.

        RU: Устанавливает non-persistent fact для одного либо всех hosts play.

        Args / Параметры:
            task (Task): Current task used to invalidate queued variables. / Текущая task.
            variable_name (str): Top-level variable name. / Имя top-level variable.
            value (object): Parsed YAML/JSON value. / Разобранное YAML/JSON-значение.
            host_name (str or None): Target host; ``None`` means all play hosts. /
                Целевой host; ``None`` означает все hosts play.
            task_vars_by_host (dict): Per-prompt variable cache. / Cache variables prompt.

        Returns / Возвращает:
            list: Host names updated; empty on validation failure. /
                Имена обновлённых hosts либо пустой list при ошибке.
        """
        if host_name is not None:
            if host_name not in self._hosts_cache:
                self._display.display("Host '%s' is not active in the current play" % host_name)
                return []
            target_host_names = [host_name]
        else:
            target_host_names = list(self._hosts_cache)

        if not target_host_names:
            self._display.warning('No active hosts to update')
            return []

        for target_host_name in target_host_names:
            self._variable_manager.set_nonpersistent_facts(
                target_host_name,
                {variable_name: value},
            )
            # EN: Invalidate both the prompt cache and vars already prepared for queueing.
            # RU: Сбрасываем cache prompt и variables, уже подготовленные для queueing.
            task_vars_by_host.pop(target_host_name, None)
            self._inspect_task_var_refresh.add((task._uuid, target_host_name))

        self._display.display(
            "SET %s for hosts: %s" % (variable_name, ', '.join(target_host_names))
        )
        return target_host_names

    def _show_args(self, task, task_vars, reveal_secrets=False):
        """Template current task arguments and display the diagnostic result.

        RU: Выполняет templating аргументов текущей task и показывает результат.

        Args / Параметры:
            task (Task): Current task. / Текущая task.
            task_vars (dict or None): Effective variables. / Effective variables.
            reveal_secrets (bool): Disable heuristic masking. / Отключить masking secrets.

        Returns / Возвращает:
            None: Templating errors fall back to raw args and emit a warning. /
                При ошибке выводятся raw args и warning.
        """
        if task_vars is None:
            self._display.warning('Task variables are unavailable')
            return
        if reveal_secrets:
            self._display.warning('secret masking disabled')
        try:
            templar = Templar(loader=self._loader, variables=task_vars)
            templated_args = templar.template(task.args)
        except Exception as exc:
            self._display.warning('Cannot template task args: %s' % to_text(exc))
            templated_args = task.args
        self._display_value(templated_args, mask_secrets=not reveal_secrets)

    def _show_expression(self, expression, host, task_vars):
        ok, value = self._evaluate_expression(expression, task_vars)
        if not ok:
            self._display.warning(
                'Cannot evaluate expression for %s: %s'
                % (host.get_name(), value)
            )
            return

        self._display.display('EVAL [%s] =' % host.get_name())
        if isinstance(value, str):
            self._display.display(to_text(value, errors='surrogate_then_replace'))
        else:
            self._display_value(value, json_format=True)

    def _show_lookup_expression(self, expression, host, task_vars):
        """Explicitly evaluate one expression with Ansible lookup plugins enabled.

        RU: Явно вычисляет expression с включёнными lookup plugins Ansible.

        Args / Параметры:
            expression (str): Trusted Jinja expression. / Доверенное Jinja-expression.
            host (Host): Host variable context and result label. / Host контекста и подписи.
            task_vars (dict or None): Effective variables. / Effective variables.

        Returns / Возвращает:
            None: Lookup errors are printed; results are intentionally unmasked. /
                Ошибки lookup выводятся; results намеренно не маскируются.
        """
        self._display.display(
            'WARNING: EVAL-LOOKUP [%s] enables Ansible lookup plugins.\n'
            '  Lookups run on the controller and may read files, run commands, access '
            'the network or external systems, or cause side effects.\n'
            '  The task may execute the lookup again. The result is not secret-masked.'
            % host.get_name()
        )
        ok, value = self._evaluate_expression(
            expression,
            task_vars,
            disable_lookups=False,
        )
        if not ok:
            self._display.warning(
                'Cannot evaluate lookup expression for %s: %s'
                % (host.get_name(), value)
            )
            return

        self._display.display('EVAL-LOOKUP [%s] =' % host.get_name())
        if isinstance(value, str):
            self._display.display(to_text(value, errors='surrogate_then_replace'))
        else:
            self._display_value(value, json_format=True)

    def _render_template(self, task, task_vars):
        """Render a built-in template task without writing its remote destination.

        RU: Рендерит built-in template task без записи remote destination.

        Args / Параметры:
            task (Task): ``template`` task to preview. / Preview task ``template``.
            task_vars (dict): Effective variables for one host/item. / Effective variables.

        Returns / Возвращает:
            tuple: ``(content, source_path, destination, output_encoding)``. /
                ``(content, source_path, destination, output_encoding)``.

        Raises / Исключения:
            ValueError: Task type or required template arguments are invalid. /
                Неверный тип task или обязательные аргументы template.
            AnsibleError: Source lookup or Jinja rendering fails. /
                Ошибка поиска source или Jinja rendering.
        """
        if task.action not in TEMPLATE_ACTIONS:
            raise ValueError('current task does not use ansible.builtin.template')
        if task_vars is None:
            raise ValueError('task variables are unavailable')

        templar = Templar(loader=self._loader, variables=task_vars)
        templated_args = templar.template(task.args)
        # EN: Mirror the template action plugin before reading src or rendering content.
        # RU: Повторяем обработку template action plugin до чтения src и rendering.
        templated_args = _apply_action_arg_defaults(
            task.resolved_action or task.action, task, templated_args, templar,
        )
        source_name = templated_args.get('src')
        destination = templated_args.get('dest')
        if source_name is None or destination is None:
            raise ValueError('template task requires src and dest')
        if templated_args.get('state') is not None:
            raise ValueError('state cannot be specified on a template task')

        newline_sequence = templated_args.get('newline_sequence', '\n')
        escaped_sequences = {'\\n': '\n', '\\r': '\r', '\\r\\n': '\r\n'}
        newline_sequence = escaped_sequences.get(newline_sequence, newline_sequence)
        if newline_sequence not in ('\n', '\r', '\r\n'):
            raise ValueError('newline_sequence must be one of: \\n, \\r, or \\r\\n')

        source_path = self._loader.path_dwim_relative_stack(
            task.get_search_path(),
            'templates',
            source_name,
        )
        real_source_path = self._loader.get_real_file(source_path)
        try:
            with open(
                to_bytes(real_source_path, errors='surrogate_or_strict'),
                'rb',
            ) as source_file:
                template_data = to_text(
                    source_file.read(),
                    errors='surrogate_or_strict',
                )

            search_path = list(task_vars.get('ansible_search_path', []))
            search_path.extend([self._loader._basedir, os.path.dirname(source_path)])
            include_search_path = []
            for path in search_path:
                include_search_path.extend([os.path.join(path, 'templates'), path])

            template_vars = task_vars.copy()
            template_vars.update(
                generate_ansible_template_vars(
                    source_name, source_path, destination,
                    include_ansible_managed='ansible_managed' not in template_vars,
                )
            )
            overrides = {
                key: templated_args[key]
                for key in (
                    'block_start_string', 'block_end_string',
                    'variable_start_string', 'variable_end_string',
                    'comment_start_string', 'comment_end_string',
                ) if templated_args.get(key) is not None
            }
            overrides.update(
                newline_sequence=newline_sequence,
                trim_blocks=boolean(templated_args.get('trim_blocks', True), strict=False),
                lstrip_blocks=boolean(templated_args.get('lstrip_blocks', False), strict=False),
            )
            template_templar = templar.copy_with_new_env(
                searchpath=include_search_path,
                available_variables=template_vars,
            )
            content = template_templar.template(
                trust_as_template(template_data),
                preserve_trailing_newlines=True,
                escape_backslashes=False,
                overrides=overrides,
            )
            if content is None:
                content = ''
        finally:
            # EN: get_real_file may materialize a temporary decrypted source.
            # RU: get_real_file может создать временный расшифрованный source.
            self._loader.cleanup_tmp_file(
                to_bytes(real_source_path, errors='surrogate_or_strict')
            )

        output_encoding = templated_args.get('output_encoding', 'utf-8') or 'utf-8'
        return content, source_path, destination, output_encoding

    def _inspect_template(self, task, host, task_vars, local_path=None):
        """Display a rendered template or save it as a protected local preview file.

        RU: Показывает rendered template либо сохраняет защищённый локальный preview-файл.

        Args / Параметры:
            task (Task): Template task. / Template task.
            host (Host): Host naming the variable context. / Host контекста variables.
            task_vars (dict): Effective variables. / Effective variables.
            local_path (str or None): Local output path; ``None`` prints content. /
                Локальный path; ``None`` выводит content на экран.

        Returns / Возвращает:
            None: Rendering and file errors are reported as warnings. /
                Ошибки rendering и файла выводятся как warnings.
        """
        try:
            content, source_path, destination, output_encoding = self._render_template(
                task,
                task_vars,
            )
        except Exception as exc:
            self._display.warning('Cannot render template preview: %s' % to_text(exc))
            return

        self._display.warning('Template preview is unmasked and may contain secrets')
        host_name = host.get_name()
        if local_path is None:
            delimiter_prefix = '' if content.endswith('\n') else '\n'
            self._display.display(
                'TEMPLATE PREVIEW [%s]\nSource: %s\nDestination: %s\n'
                '----- BEGIN TEMPLATE -----\n%s%s----- END TEMPLATE -----'
                % (host_name, source_path, destination, content, delimiter_prefix)
            )
            return

        save_path = os.path.abspath(os.path.expanduser(local_path))
        file_created = False
        descriptor = None
        try:
            encoded_content = to_bytes(
                content,
                encoding=output_encoding,
                errors='surrogate_or_strict',
            )
            # EN: O_EXCL prevents accidental overwrite; mode 0600 protects preview secrets.
            # RU: O_EXCL исключает overwrite, а mode 0600 защищает secrets preview.
            descriptor = os.open(
                to_bytes(save_path, errors='surrogate_or_strict'),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            file_created = True
            os.fchmod(descriptor, 0o600)
            preview_file = os.fdopen(descriptor, 'wb')
            descriptor = None
            with preview_file:
                preview_file.write(encoded_content)
        except FileExistsError:
            self._display.warning(
                'Cannot save template preview: file already exists: %s' % save_path
            )
            return
        except Exception as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as close_exc:
                    self._display.warning(
                        'Cannot close incomplete template preview %s: %s'
                        % (save_path, to_text(close_exc))
                    )
            if file_created:
                try:
                    os.unlink(to_bytes(save_path, errors='surrogate_or_strict'))
                except OSError as cleanup_exc:
                    self._display.warning(
                        'Cannot remove incomplete template preview %s: %s'
                        % (save_path, to_text(cleanup_exc))
                    )
            self._display.warning('Cannot save template preview: %s' % to_text(exc))
            return

        self._display.display(
            'TEMPLATE SAVED [%s]\nSource: %s\nDestination: %s\nLocal file: %s'
            % (host_name, source_path, destination, save_path)
        )

    def _resolve_inspection_host(self, host_name, default_host):
        """Resolve an explicit active host or fall back to the default inspection host.

        RU: Разрешает явно выбранный active host либо возвращает default inspection host.

        Args / Параметры:
            host_name (str or None): Explicit host name. / Явное имя host.
            default_host (Host or None): Fallback host. / Host по умолчанию.

        Returns / Возвращает:
            Host or None: Resolved host; invalid hosts are reported and return ``None``. /
                Найденный host; при ошибке выводится сообщение и возвращается ``None``.
        """
        if host_name is None:
            return default_host
        if host_name not in self._hosts_cache:
            self._display.display("Host '%s' is not active in the current play" % host_name)
            return None

        host = self._inventory.get_host(host_name)
        if host is None:
            self._display.display("Host '%s' is undefined" % host_name)
        return host

    def _vars_for_inspection_host(self, task, host, task_vars_by_host):
        """Return cached variables for one host, collecting them on first use.

        RU: Возвращает cached variables host, собирая их при первом обращении.

        Args / Параметры:
            task (Task): Current task. / Текущая task.
            host (Host or None): Requested host. / Запрошенный host.
            task_vars_by_host (dict): Mutable per-prompt cache. / Изменяемый cache prompt.

        Returns / Возвращает:
            dict or None: Effective variables, or ``None`` after a collection error. /
                Effective variables либо ``None`` после ошибки сбора.
        """
        if host is None:
            return None

        host_name = host.get_name()
        if host_name not in task_vars_by_host:
            try:
                task_vars_by_host[host_name] = self._get_task_vars(task, host)
            except Exception as exc:
                self._display.warning(
                    'Cannot collect task variables for %s: %s' % (host_name, to_text(exc))
                )
                task_vars_by_host[host_name] = None
        return task_vars_by_host[host_name]

    def _show_hosts(self, task_hosts, inspect_host):
        self._display.display('HOSTS IN CURRENT PLAY (--limit applied)')
        if not self._hosts_cache:
            self._display.display('  none')
            return

        task_host_names = {host.get_name() for host in task_hosts}
        default_host_name = inspect_host.get_name() if inspect_host is not None else None
        for host_name in self._hosts_cache:
            labels = []
            if host_name == default_host_name:
                labels.append('default inspection host')
            if host_name in task_host_names:
                labels.append('active for current task')
            suffix = ' (%s)' % ', '.join(labels) if labels else ''
            self._display.display('  %s%s' % (host_name, suffix))

    def _show_when_for_host(self, task, host, task_vars):
        """Evaluate task conditions in order for one host and show RUN or SKIP.

        RU: Последовательно вычисляет conditions task для host и показывает RUN или SKIP.

        Args / Параметры:
            task (Task): Task containing ``when`` conditions. / Task с conditions ``when``.
            host (Host): Host used for the result label. / Host для подписи результата.
            task_vars (dict or None): Effective variables. / Effective variables.

        Returns / Возвращает:
            None: Undefined variables and evaluation errors are printed as diagnostics. /
                Undefined variables и ошибки выводятся как диагностика.
        """
        host_name = host.get_name()
        conditions = list(task.when or [])
        if not conditions:
            self._display.display('WHEN [%s]: RUN (no conditions)' % host_name)
            return
        if task_vars is None:
            self._display.display('WHEN [%s]: ERROR (task variables unavailable)' % host_name)
            return

        overall = True
        for index, condition in enumerate(conditions, 1):
            condition_text = to_text(condition, errors='surrogate_then_replace')
            if not overall:
                # EN: Match Ansible's left-to-right short-circuit behavior.
                # RU: Повторяем left-to-right short-circuit семантику Ansible.
                self._display.display(
                    '  %d. NOT EVALUATED (short-circuit): %s'
                    % (index, condition_text)
                )
                continue
            templar = Templar(loader=self._loader, variables=task_vars)
            try:
                matched = templar.evaluate_conditional(condition)
            except Exception as exc:
                self._display.display(
                    '  %d. ERROR: %s\n     %s'
                    % (index, condition_text, to_text(exc))
                )
                self._display.display('WHEN [%s]: ERROR' % host_name)
                return
            self._display.display(
                '  %d. %s: %s'
                % (index, 'TRUE' if matched else 'FALSE', condition_text)
            )
            overall = overall and matched
        self._display.display('WHEN [%s]: %s' % (host_name, 'RUN' if overall else 'SKIP'))

    def _show_when(self, task, hosts, inspect_host, target, task_vars_by_host):
        """Evaluate current task conditions for a selected host set.

        RU: Вычисляет conditions текущей task для выбранной группы hosts.

        Args / Параметры:
            task (Task): Current task. / Текущая task.
            hosts (list): Hosts active for the task. / Активные hosts task.
            inspect_host (Host or None): Default host. / Default host.
            target (str or None): Explicit host, ``all``, or default. / Host, ``all`` или default.
            task_vars_by_host (dict): Per-prompt variable cache. / Cache variables prompt.

        Returns / Возвращает:
            None: Each host result is displayed independently. / Result каждого host выводится.
        """
        if target == 'all':
            target_hosts = hosts
        else:
            command_host = self._resolve_inspection_host(target, inspect_host)
            target_hosts = [command_host] if command_host is not None else []
        if not target_hosts:
            self._display.warning('No host is available for when evaluation')
            return
        for target_host in target_hosts:
            task_vars = self._vars_for_inspection_host(
                task,
                target_host,
                task_vars_by_host,
            )
            self._show_when_for_host(task, target_host, task_vars)

    def _loop_items_for_preview(self, task, task_vars):
        """Expand modern ``loop`` or legacy ``with_*`` terms for preview.

        RU: Раскрывает modern ``loop`` или legacy ``with_*`` для preview.

        Args / Параметры:
            task (Task): Loop task. / Task с loop.
            task_vars (dict): Effective variables for one host. / Effective variables host.

        Returns / Возвращает:
            tuple: ``(items, preview_vars, templar)`` used by later item diagnostics. /
                ``(items, preview_vars, templar)`` для последующей диагностики items.

        Raises / Исключения:
            AnsibleError: Lookup is missing or modern loop does not expand to a list. /
                Lookup не найден либо modern loop раскрывается не в list.
        """
        preview_vars = task_vars.copy()
        search_path = list(task.get_search_path())
        basedir = self._loader.get_basedir()
        if basedir not in search_path:
            search_path.append(basedir)
        preview_vars['ansible_search_path'] = search_path

        templar = Templar(loader=self._loader, variables=preview_vars)
        # EN: Includes may expose executor-expanded items through this private cache.
        # RU: Includes могут передать раскрытые executor items через этот внутренний cache.
        loop_cache = preview_vars.get('_ansible_loop_cache')
        if loop_cache is not None:
            items = loop_cache
        elif task.loop_with:
            # EN: Legacy with_* is a real lookup and may have controller-side effects.
            # RU: Legacy with_* является lookup и может иметь controller-side effects.
            if task.loop_with not in lookup_loader:
                raise AnsibleError(
                    "Unexpected failure in finding the lookup named '%s'"
                    % task.loop_with
                )
            from ansible._internal._templating._jinja_plugins import _invoke_lookup, _DirectCall

            terms = task.loop
            if isinstance(terms, str):
                terms = templar.template(terms.strip())
            if not isinstance(terms, list):
                terms = [terms]

            @_DirectCall.mark
            def invoke_lookup():
                return _invoke_lookup(
                    plugin_name=task.loop_with,
                    lookup_terms=terms,
                    lookup_kwargs={'wantlist': True},
                    invoked_as_with=True,
                )

            items = templar.evaluate_expression(
                trust_as_template('invoke_lookup()'),
                local_variables={'invoke_lookup': invoke_lookup},
            )

        else:
            items = templar.template(task.loop)
            if not isinstance(items, list):
                raise AnsibleError(
                    "Invalid data passed to 'loop': expected a list, got %s"
                    % type(items).__name__
                )
        return items, preview_vars, templar

    def _loop_control_for_preview(self, task, templar):
        loop_var = 'item'
        index_var = None
        extended = False
        label = None
        if task.loop_control:
            loop_var = templar.template(task.loop_control.loop_var)
            index_var = templar.template(task.loop_control.index_var)
            extended = bool(templar.template(task.loop_control.extended))
            label = task.loop_control.label
        return loop_var, index_var, extended, label

    def _extended_loop_vars(self, items, item_index):
        items_len = len(items)
        loop_vars = {
            'allitems': items,
            'index': item_index + 1,
            'index0': item_index,
            'first': item_index == 0,
            'last': item_index + 1 == items_len,
            'length': items_len,
            'revindex': items_len - item_index,
            'revindex0': items_len - item_index - 1,
        }
        if item_index + 1 < items_len:
            loop_vars['nextitem'] = items[item_index + 1]
        if item_index > 0:
            loop_vars['previtem'] = items[item_index - 1]
        return loop_vars

    def _loop_item_variables(
        self,
        items,
        preview_vars,
        loop_var,
        index_var,
        extended,
        item_index,
    ):
        """Build the loop variables that TaskExecutor would expose for one item.

        RU: Формирует loop variables, которые TaskExecutor создаёт для одного item.

        Args / Параметры:
            items (list): Expanded loop items. / Раскрытые items loop.
            preview_vars (dict): Base host variables. / Базовые variables host.
            loop_var (str): Effective item variable name. / Имя variable item.
            index_var (str or None): Optional zero-based index variable. / Index variable.
            extended (bool): Add ``ansible_loop`` metadata. / Добавить ``ansible_loop``.
            item_index (int): Zero-based selected index. / Zero-based индекс item.

        Returns / Возвращает:
            dict: Independent variable mapping for the selected item. /
                Независимый mapping variables выбранного item.

        Raises / Исключения:
            IndexError: ``item_index`` is outside ``items``. / Индекс выходит за ``items``.
        """
        item_vars = preview_vars.copy()
        # EN: Keep these names aligned with ansible.executor.task_executor.TaskExecutor.
        # RU: Имена должны соответствовать ansible.executor.task_executor.TaskExecutor.
        item_vars['ansible_loop_var'] = loop_var
        item_vars[loop_var] = items[item_index]
        if index_var:
            item_vars['ansible_index_var'] = index_var
            item_vars[index_var] = item_index
        if extended:
            item_vars['ansible_loop'] = self._extended_loop_vars(items, item_index)
        return item_vars

    def _parse_loop_item_command(self, response):
        """Parse an item-aware ``loop eval|when|args|template`` command.

        RU: Разбирает item-aware команду ``loop eval|when|args|template``.

        Args / Параметры:
            response (str): Complete inspector command. / Полная команда inspector.

        Returns / Возвращает:
            tuple: ``(operation, item_number, expression, host_name)``. /
                ``(operation, item_number, expression, host_name)``.

        Raises / Исключения:
            ValueError: Syntax, item number, expression, or trailing arguments are invalid. /
                Неверны syntax, номер item, expression или trailing arguments.
        """
        match = re.match(
            r'^loop\s+(eval|when|args|template)\s+(\S+)(?:\s+(.*))?$',
            response,
            flags=re.IGNORECASE,
        )
        if match is None:
            raise ValueError('operation and item number are required')

        operation = match.group(1).lower()
        try:
            item_number = int(match.group(2))
        except ValueError:
            raise ValueError('item number must be a positive integer')
        if item_number < 1:
            raise ValueError('item number must be a positive integer')

        remainder = (match.group(3) or '').strip()
        host_name = None
        host_match = re.search(r'(?:^|\s)host=([^\s]+)\s*$', remainder)
        if host_match is not None:
            host_name = host_match.group(1)
            remainder = remainder[:host_match.start()].rstrip()

        if operation == 'eval':
            if not remainder:
                raise ValueError('Jinja expression is required')
            expression = remainder
        else:
            if remainder:
                raise ValueError("unexpected argument '%s'" % remainder)
            expression = None
        return operation, item_number, expression, host_name

    def _prepare_loop_item_context(self, task, task_vars, item_number):
        """Expand a loop and create effective variables for one 1-based item number.

        RU: Раскрывает loop и создаёт effective variables для item с 1-based номером.

        Args / Параметры:
            task (Task): Current loop task. / Текущая loop-task.
            task_vars (dict): Effective host variables. / Effective variables host.
            item_number (int): Selected 1-based item number. / 1-based номер item.

        Returns / Возвращает:
            tuple: ``(item_vars, item, items_len, loop_var)``. /
                ``(item_vars, item, items_len, loop_var)``.

        Raises / Исключения:
            ValueError: Task has no loop, variables are unavailable, or range is invalid. /
                Нет loop/variables либо номер выходит за range.
            AnsibleError: Loop expansion fails. / Ошибка раскрытия loop.
        """
        if task.loop is None and not task.loop_with:
            raise ValueError('current task does not define a loop')
        if task_vars is None:
            raise ValueError('task variables are unavailable')
        if item_number < 1:
            raise ValueError('item number must be a positive integer')

        items, preview_vars, templar = self._loop_items_for_preview(task, task_vars)
        try:
            items_len = len(items)
        except (TypeError, AttributeError):
            raise ValueError('expanded loop value has no length')
        if item_number > items_len:
            raise ValueError(
                'item %d is outside the available range 1..%d'
                % (item_number, items_len)
            )

        loop_var, index_var, extended, _label = self._loop_control_for_preview(
            task,
            templar,
        )
        item_index = item_number - 1
        item_vars = self._loop_item_variables(
            items,
            preview_vars,
            loop_var,
            index_var,
            extended,
            item_index,
        )
        return item_vars, items[item_index], items_len, loop_var

    def _inspect_loop_item(
        self,
        task,
        inspect_host,
        task_vars_by_host,
        operation,
        item_number,
        expression,
        host_name,
    ):
        """Run one diagnostic operation in a selected host/item context.

        RU: Выполняет одну диагностическую операцию в выбранном host/item-контексте.

        Args / Параметры:
            task (Task): Current loop task. / Текущая loop-task.
            inspect_host (Host or None): Default inspection host. / Default host inspector.
            task_vars_by_host (dict): Per-prompt variable cache. / Cache variables prompt.
            operation (str): ``eval``, ``when``, ``args``, or ``template``. / Операция.
            item_number (int): Selected 1-based item. / Выбранный 1-based item.
            expression (str or None): Jinja text for ``eval``. / Jinja для ``eval``.
            host_name (str or None): Explicit host override. / Явный host.

        Returns / Возвращает:
            None: Preparation and evaluation errors are shown without leaving the prompt. /
                Ошибки показываются без выхода из prompt.
        """
        host = self._resolve_inspection_host(host_name, inspect_host)
        if host is None:
            if host_name is None:
                self._display.warning('Inspection host is unavailable')
            return

        self._display.warning(
            'Loop item inspection evaluates task templating and may execute '
            'controller-side lookups'
        )
        task_vars = self._vars_for_inspection_host(
            task,
            host,
            task_vars_by_host,
        )
        try:
            item_vars, item, items_len, loop_var = self._prepare_loop_item_context(
                task,
                task_vars,
                item_number,
            )
        except Exception as exc:
            self._display.warning(
                'Cannot prepare loop item context for %s: %s'
                % (host.get_name(), to_text(exc))
            )
            return

        self._display.display(
            'LOOP ITEM CONTEXT [%s] ITEM %d/%d\n  %s ='
            % (host.get_name(), item_number, items_len, loop_var)
        )
        self._display_value(item, mask_secrets=True, json_format=True)

        if operation == 'eval':
            self._show_expression(expression, host, item_vars)
        elif operation == 'when':
            self._show_when_for_host(task, host, item_vars)
        elif operation == 'args':
            self._show_args(task, item_vars)
        else:
            self._inspect_template(task, host, item_vars)

    def _show_loop_for_host(
        self,
        task,
        host,
        task_vars,
        reveal_secrets=False,
        max_depth=None,
    ):
        """Expand and display loop items plus loop-control metadata for one host.

        RU: Раскрывает и показывает items и metadata loop-control для одного host.

        Args / Параметры:
            task (Task): Current loop task. / Текущая loop-task.
            host (Host): Host variable context. / Host контекста variables.
            task_vars (dict or None): Effective variables. / Effective variables.
            reveal_secrets (bool): Disable heuristic masking. / Отключить masking secrets.
            max_depth (int or None): Maximum item display depth. / Глубина вывода item.

        Returns / Возвращает:
            None: Expansion and label errors are displayed inline. /
                Ошибки раскрытия и label выводятся inline.
        """
        if task_vars is None:
            self._display.display(
                'LOOP PREVIEW [%s]: ERROR (task variables unavailable)'
                % host.get_name()
            )
            return
        try:
            items, preview_vars, templar = self._loop_items_for_preview(task, task_vars)
            loop_var, index_var, extended, label = self._loop_control_for_preview(
                task,
                templar,
            )
        except Exception as exc:
            self._display.display(
                'LOOP PREVIEW [%s]: ERROR\n  %s'
                % (host.get_name(), to_text(exc))
            )
            return
        try:
            items_len = len(items)
        except (TypeError, AttributeError):
            self._display.display(
                'LOOP PREVIEW [%s]: ERROR\n  expanded loop value has no length'
                % host.get_name()
            )
            return

        source = 'with_%s' % task.loop_with if task.loop_with else 'loop'
        self._display.display(
            'LOOP PREVIEW [%s]: %d items\n'
            '  source: %s\n'
            '  loop_var: %s'
            % (host.get_name(), items_len, source, loop_var)
        )
        if index_var:
            self._display.display('  index_var: %s (zero-based)' % index_var)
        if extended:
            self._display.display('  extended: true')

        for item_index, item in enumerate(items):
            item_vars = self._loop_item_variables(
                items,
                preview_vars,
                loop_var,
                index_var,
                extended,
                item_index,
            )

            self._display.display(
                '  ITEM %d/%d' % (item_index + 1, items_len)
            )
            if index_var:
                self._display.display('  %s = %d' % (index_var, item_index))
            if label is not None:
                templar.available_variables = item_vars
                try:
                    label_value = templar.template(label)
                except Exception as exc:
                    label_value = '<label error: %s>' % to_text(exc)
                if not reveal_secrets and _key_contains_secret(label):
                    label_value = HIDDEN_VALUE
                self._display.display('  label =')
                self._display_value(
                    label_value,
                    mask_secrets=not reveal_secrets,
                    json_format=True,
                    max_depth=max_depth,
                )
            self._display.display('  %s =' % loop_var)
            self._display_value(
                item,
                mask_secrets=not reveal_secrets,
                json_format=True,
                max_depth=max_depth,
            )

    def _show_loop_preview(
        self,
        task,
        hosts,
        inspect_host,
        target,
        task_vars_by_host,
        reveal_secrets=False,
        max_depth=None,
    ):
        """Display expanded loop items for one host or all current task hosts.

        RU: Показывает раскрытые items loop для одного или всех hosts текущей task.

        Args / Параметры:
            task (Task): Current loop task. / Текущая loop-task.
            hosts (list): Hosts active for the task. / Активные hosts task.
            inspect_host (Host or None): Default host. / Default host.
            target (str or None): Explicit host, ``all``, or default. / Host, ``all`` или default.
            task_vars_by_host (dict): Per-prompt variable cache. / Cache variables prompt.
            reveal_secrets (bool): Disable heuristic masking. / Отключить masking secrets.
            max_depth (int or None): Maximum item display depth. / Глубина вывода items.

        Returns / Возвращает:
            None: Expansion errors are displayed per host. / Ошибки выводятся для host.
        """
        if task.loop is None and not task.loop_with:
            self._display.display('Current task does not define a loop')
            return
        if reveal_secrets:
            self._display.warning('secret masking disabled')
        self._display.warning(
            'Loop preview evaluates task templating and may execute controller-side lookups'
        )

        if target == 'all':
            target_hosts = hosts
        else:
            command_host = self._resolve_inspection_host(target, inspect_host)
            target_hosts = [command_host] if command_host is not None else []
        if not target_hosts:
            self._display.warning('No host is available for loop preview')
            return
        for target_host in target_hosts:
            task_vars = self._vars_for_inspection_host(
                task,
                target_host,
                task_vars_by_host,
            )
            self._show_loop_for_host(
                task,
                target_host,
                task_vars,
                reveal_secrets=reveal_secrets,
                max_depth=max_depth,
            )

    def _parse_watch_add(self, response):
        """Parse ``watch add EXPRESSION [host=HOST]``.

        RU: Разбирает ``watch add EXPRESSION [host=HOST]``.

        Args / Параметры:
            response (str): Complete command. / Полная команда.

        Returns / Возвращает:
            tuple: ``(expression, host_name)``. / ``(expression, host_name)``.

        Raises / Исключения:
            ValueError: Expression is missing or host is inactive. /
                Expression отсутствует либо host неактивен.
        """
        match = re.match(r'^watch\s+add\s+(.+)$', response, flags=re.IGNORECASE)
        if match is None:
            raise ValueError('expression is required')
        expression = match.group(1).strip()
        host_name = None
        host_match = re.search(r'(?:^|\s)host=([^\s]+)\s*$', expression)
        if host_match is not None:
            host_name = host_match.group(1)
            expression = expression[:host_match.start()].rstrip()
            if host_name not in self._hosts_cache:
                raise ValueError("host '%s' is not active in the current play" % host_name)
        if not expression:
            raise ValueError('expression is required')
        return expression, host_name

    def _add_watch(self, expression, host_name):
        watch = {
            'id': self._inspect_next_watch_id,
            'expression': expression,
            'host': host_name,
        }
        self._inspect_next_watch_id += 1
        self._inspect_watches.append(watch)
        self._display.display('WATCH #%d added' % watch['id'])

    def _list_watches(self):
        if not self._inspect_watches:
            self._display.display('No watches are defined')
            return
        self._display.display('WATCHES')
        for watch in self._inspect_watches:
            host_label = watch['host'] or '<inspection host>'
            self._display.display(
                '  #%d host=%s: %s'
                % (watch['id'], host_label, watch['expression'])
            )

    def _delete_watch(self, watch_id):
        for watch in self._inspect_watches:
            if watch['id'] == watch_id:
                self._inspect_watches.remove(watch)
                self._display.display('WATCH #%d deleted' % watch_id)
                return
        self._display.display('Watch #%d is undefined' % watch_id)

    def _show_watches(self, task, inspect_host, task_vars_by_host):
        """Evaluate all watches at a task stop with lookup plugins disabled.

        RU: Вычисляет все watches при остановке task с отключёнными lookup plugins.

        Args / Параметры:
            task (Task): Current task. / Текущая task.
            inspect_host (Host or None): Default host. / Default host.
            task_vars_by_host (dict): Per-prompt variable cache. / Cache variables prompt.

        Returns / Возвращает:
            None: Individual errors are displayed beside each watch. /
                Ошибки выводятся рядом с соответствующим watch.
        """
        if not self._inspect_watches:
            return
        self._display.display('\nWATCH VALUES (unmasked; lookups disabled)')
        for watch in self._inspect_watches:
            host = self._resolve_inspection_host(watch['host'], inspect_host)
            if host is None:
                self._display.display('WATCH #%d: host unavailable' % watch['id'])
                continue
            task_vars = self._vars_for_inspection_host(task, host, task_vars_by_host)
            ok, value = self._evaluate_expression(watch['expression'], task_vars)
            self._display.display(
                'WATCH #%d [%s] %s ='
                % (watch['id'], host.get_name(), watch['expression'])
            )
            if not ok:
                self._display.display('ERROR: %s' % value)
            elif isinstance(value, str):
                self._display.display(to_text(value, errors='surrogate_then_replace'))
            else:
                self._display_value(value, json_format=True)

    def _parse_breakpoint_definition(self, response):
        """Parse a task-regexp, role, or tag breakpoint definition.

        RU: Разбирает breakpoint по task-regexp, role или tag.

        Args / Параметры:
            response (str): Complete ``break`` command. / Полная команда ``break``.

        Returns / Возвращает:
            tuple: ``(breakpoint_type, breakpoint_value)``. /
                ``(breakpoint_type, breakpoint_value)``.

        Raises / Исключения:
            ValueError: Type, quoting, or value is invalid. / Неверны type, quoting или value.
        """
        match = re.match(
            r'^break\s+(task|role|tag)\s+(.+)$',
            response,
            flags=re.IGNORECASE,
        )
        if match is None:
            raise ValueError('breakpoint type and value are required')

        breakpoint_type = match.group(1).lower()
        breakpoint_value = match.group(2).strip()
        if breakpoint_value.startswith(("'", '"')):
            try:
                quoted_values = shlex.split(breakpoint_value)
            except ValueError as exc:
                raise ValueError('cannot parse quoted value: %s' % to_text(exc))
            if len(quoted_values) != 1:
                raise ValueError('a quoted breakpoint must contain one value')
            breakpoint_value = quoted_values[0]
        if not breakpoint_value:
            raise ValueError('breakpoint value must not be empty')
        return breakpoint_type, breakpoint_value

    def _add_breakpoint(self, breakpoint_type, value):
        """Validate and store one breakpoint in the current inspector process.

        RU: Проверяет и сохраняет breakpoint в текущем процессе inspector.

        Args / Параметры:
            breakpoint_type (str): ``task``, ``role``, or ``tag``. / Тип breakpoint.
            value (str): Regexp or exact match value. / Regexp либо exact value.

        Returns / Возвращает:
            None: The assigned ID is displayed. / Назначенный ID выводится на экран.

        Raises / Исключения:
            ValueError: A task regular expression cannot be compiled. /
                Regexp task не компилируется.
        """
        compiled = None
        if breakpoint_type == 'task':
            try:
                compiled = re.compile(value)
            except re.error as exc:
                raise ValueError('invalid task regexp: %s' % to_text(exc))
        breakpoint = {
            'id': self._inspect_next_breakpoint_id,
            'type': breakpoint_type,
            'value': value,
            'compiled': compiled,
        }
        self._inspect_next_breakpoint_id += 1
        self._inspect_breakpoints.append(breakpoint)
        self._display.display('BREAKPOINT #%d added' % breakpoint['id'])

    def _add_task_catalog_breakpoint(self, task_id):
        """Add an exact UUID breakpoint selected from the visible task catalog."""
        entry = self._inspect_task_catalog_by_id.get(task_id)
        if entry is None:
            raise ValueError("task ID %d is undefined; run 'tasks' first" % task_id)
        if not entry['selectable']:
            raise ValueError(
                'task ID %d is a static import group and has no runtime stop' % task_id
            )
        breakpoint = {
            'id': self._inspect_next_breakpoint_id,
            'type': 'task-id',
            'value': entry['name'],
            'compiled': None,
            'task_id': task_id,
            'task_uuid': entry['uuid'],
        }
        self._inspect_next_breakpoint_id += 1
        self._inspect_breakpoints.append(breakpoint)
        self._display.display(
            'BREAKPOINT #%d added for task [%03d] %s'
            % (breakpoint['id'], task_id, entry['name'])
        )

    def _list_breakpoints(self):
        if not self._inspect_breakpoints:
            self._display.display('No breakpoints are defined')
            return
        self._display.display('BREAKPOINTS')
        for breakpoint in self._inspect_breakpoints:
            if breakpoint['type'] == 'task-id':
                self._display.display(
                    '  #%d task-id: [%03d] %s'
                    % (
                        breakpoint['id'],
                        breakpoint['task_id'],
                        breakpoint['value'],
                    )
                )
            else:
                self._display.display(
                    '  #%d %s: %s'
                    % (breakpoint['id'], breakpoint['type'], breakpoint['value'])
                )

    def _delete_breakpoint(self, breakpoint_id):
        for breakpoint in self._inspect_breakpoints:
            if breakpoint['id'] == breakpoint_id:
                self._inspect_breakpoints.remove(breakpoint)
                self._display.display('BREAKPOINT #%d deleted' % breakpoint_id)
                return
        self._display.display('Breakpoint #%d is undefined' % breakpoint_id)

    def _matching_breakpoints(self, task):
        """Return every configured breakpoint matching a task, role, or tag.

        RU: Возвращает все breakpoints, совпавшие с task, role или tag.

        Args / Параметры:
            task (Task): Candidate task. / Проверяемая task.

        Returns / Возвращает:
            list: Matching breakpoint dictionaries. / Совпавшие breakpoint mappings.
        """
        matches = []
        role = getattr(task, '_role', None)
        role_names = set()
        if role is not None:
            role_names.add(role.get_name())
            role_names.add(role.get_name(include_role_fqcn=False))
        task_tags = set(to_text(tag) for tag in (task.tags or []))
        task_name = task.get_name()
        for breakpoint in self._inspect_breakpoints:
            if (
                breakpoint['type'] == 'task-id'
                and breakpoint['task_uuid'] == task._uuid
            ):
                matches.append(breakpoint)
            elif breakpoint['type'] == 'task' and breakpoint['compiled'].search(task_name):
                matches.append(breakpoint)
            elif breakpoint['type'] == 'role' and breakpoint['value'] in role_names:
                matches.append(breakpoint)
            elif breakpoint['type'] == 'tag' and breakpoint['value'] in task_tags:
                matches.append(breakpoint)
        return matches

    def _show_task_source(self, task):
        """Display the original task definition with heuristic secret masking.

        RU: Показывает исходное определение task с эвристическим masking secrets.

        Args / Параметры:
            task (Task): Task whose data source is requested. / Task для показа source.

        Returns / Возвращает:
            None: Missing source and serialization errors are reported as warnings. /
                Отсутствующий source и ошибки serialization выводятся как warnings.
        """
        task_data = task.get_ds()
        if task_data is None:
            self._display.warning('Original task definition is unavailable')
            return

        try:
            safe_task_data = _mask_secrets(task_data)
            rendered = yaml.dump(
                [safe_task_data],
                Dumper=AnsibleDumper,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ).rstrip()
        except Exception as exc:
            self._display.warning('Cannot render original task definition: %s' % to_text(exc))
            return

        source_path = task.get_path() or 'unknown source'
        self._display.display('\nTASK SOURCE [%s] (secrets masked)\n%s' % (source_path, rendered))

    def _take_step(self, task, host=None):
        """Run the interactive pre-queue command loop for one lockstep task.

        RU: Запускает интерактивный command loop перед queueing одной lockstep-task.

        Args / Параметры:
            task (Task): Task waiting for an execution decision. / Task до решения о запуске.
            host (Host or str or None): Optional host for handler/special paths. /
                Необязательный host для handler или специальных paths.

        Returns / Возвращает:
            bool: ``True`` queues the task; ``False`` skips it. /
                ``True`` ставит task в очередь, ``False`` пропускает её.

        Error conditions / Ошибки:
            EOF safely skips the task; command errors stay in the same prompt. /
                EOF безопасно пропускает task; ошибки команд не закрывают prompt.
        """
        if isinstance(task, Handler) and self._inspect_run_all_flushing_handlers:
            return True
        if self._inspect_run_all_include is not None:
            include_scope = self._inspect_run_all_include
            if self._is_within_include(task, include_scope['uuid']):
                return True
            self._inspect_run_all_include = None
            self._display.display(
                '\nRUN ALL COMPLETE: %s' % include_scope['name']
            )

        if self._inspect_go:
            matching_breakpoints = self._matching_breakpoints(task)
            if not matching_breakpoints:
                return True
            self._inspect_go = False
            self._display.display(
                '\nBREAKPOINT HIT: %s'
                % ', '.join('#%d' % item['id'] for item in matching_breakpoints)
            )

        # EN: One prompt controls the complete lockstep host batch, not one host at a time.
        # RU: Один prompt управляет всей lockstep-группой hosts, а не отдельным host.
        hosts = self._hosts_for_task(task, host=host)
        inspect_host = hosts[0] if hosts else None
        # EN: Host variables are loaded lazily because facts/hostvars can be very large.
        # RU: Variables hosts загружаются лениво, так как facts/hostvars могут быть огромны.
        task_vars_by_host = {}
        task_vars = self._vars_for_inspection_host(task, inspect_host, task_vars_by_host)

        self._display.display('\nINSPECT TASK: %s' % task.get_name())
        if inspect_host is None:
            self._display.display('Host: unavailable')
        elif len(hosts) == 1:
            self._display.display('Host: %s' % inspect_host.get_name())
        else:
            self._display.display(
                'Host: %s (inspection host; task has %d active hosts)'
                % (inspect_host.get_name(), len(hosts))
            )

        self._show_task_source(task)
        self._show_watches(task, inspect_host, task_vars_by_host)

        while True:
            try:
                response = self._display.prompt('\ninspect-step> ').strip()
            except EOFError:
                self._display.warning('End of input; task skipped')
                return False

            command = response.lower()
            parts = response.split()
            verb = parts[0].lower() if parts else ''
            if command in ('r', 'run'):
                self._display.display('\nRUN: %s' % task.get_name())
                return True
            if command in ('r!', 'run!'):
                self._inspect_no_log_overrides[task._uuid] = set(
                    run_host.get_name() for run_host in hosts
                )
                self._display.warning(
                    'task-level no_log is disabled for this task; results and '
                    'secrets may be written to stdout and callback logs'
                )
                self._display.display(
                    '\nRUN (no_log disabled): %s' % task.get_name()
                )
                return True
            if command in ('ra', 'run-all'):
                if not self._is_dynamic_include(task):
                    self._display.display(
                        'run-all is available only for include_tasks and include_role'
                    )
                    continue
                self._inspect_run_all_include = {
                    'uuid': task._uuid,
                    'name': task.get_name(),
                }
                self._display.display('\nRUN ALL: %s' % task.get_name())
                return True
            if command in ('s', 'skip'):
                self._display.display('\nSKIP: %s' % task.get_name())
                return False
            if command in ('g', 'go'):
                if not self._inspect_breakpoints:
                    self._display.display(
                        'Cannot use go: define at least one breakpoint first'
                    )
                    continue
                self._inspect_go = True
                self._display.display('\nGO: running until a breakpoint matches')
                return True
            if command in ('c', 'continue'):
                self._inspect_go = False
                self._step = False
                self._display.display('\nRUN: %s' % task.get_name())
                return True
            if command in ('h', 'help', '?'):
                self._display.display(HELP_TEXT)
                continue
            if command == 'w':
                self._show_task_source(task)
                continue
            if command == 'hosts':
                self._show_hosts(hosts, inspect_host)
                continue
            if command == 'raw':
                self._display_value(task.args)
                continue
            if verb == 'when':
                if len(parts) > 2:
                    self._display.display('Usage: when [HOST|all]')
                    continue
                target = parts[1] if len(parts) == 2 else None
                self._show_when(
                    task,
                    hosts,
                    inspect_host,
                    target,
                    task_vars_by_host,
                )
                continue
            if (
                verb == 'loop'
                and len(parts) >= 2
                and parts[1].lower() in ('eval', 'when', 'args', 'template')
            ):
                try:
                    operation, item_number, expression, host_name = (
                        self._parse_loop_item_command(response)
                    )
                except ValueError as exc:
                    self._display.display(
                        'Invalid loop item command: %s' % to_text(exc)
                    )
                    self._display.display(
                        'Usage: loop eval ITEM JINJA_EXPRESSION [host=HOST] | '
                        'loop when|args|template ITEM [host=HOST]'
                    )
                    continue
                self._inspect_loop_item(
                    task,
                    inspect_host,
                    task_vars_by_host,
                    operation,
                    item_number,
                    expression,
                    host_name,
                )
                continue
            if verb in ('loop', 'loop!'):
                try:
                    target, max_depth = self._parse_host_depth_options(parts[1:])
                except ValueError as exc:
                    self._display.display('Invalid loop options: %s' % to_text(exc))
                    self._display.display('Usage: %s [HOST|all] [depth=N]' % verb)
                    continue
                self._show_loop_preview(
                    task,
                    hosts,
                    inspect_host,
                    target,
                    task_vars_by_host,
                    reveal_secrets=verb.endswith('!'),
                    max_depth=max_depth,
                )
                continue
            if verb in ('result', 'result!'):
                try:
                    target, max_depth = self._parse_host_depth_options(parts[1:])
                except ValueError as exc:
                    self._display.display('Invalid result options: %s' % to_text(exc))
                    self._display.display('Usage: %s [HOST|all] [depth=N]' % verb)
                    continue
                self._show_last_result(
                    target,
                    inspect_host,
                    reveal_secrets=verb.endswith('!'),
                    max_depth=max_depth,
                )
                continue
            if verb == 'eval-all':
                try:
                    expression, show_diff = self._parse_eval_all_command(response)
                except ValueError as exc:
                    self._display.display('Invalid eval-all command: %s' % to_text(exc))
                    self._display.display(
                        'Usage: eval-all JINJA_EXPRESSION [diff=true]'
                    )
                    continue
                self._show_expression_all(
                    expression,
                    hosts,
                    task,
                    task_vars_by_host,
                    show_diff=show_diff,
                )
                continue
            if verb == 'eval-lookup':
                try:
                    expression, host_name = self._parse_eval_command(response)
                except ValueError as exc:
                    self._display.display(
                        'Invalid eval-lookup command: %s' % to_text(exc)
                    )
                    self._display.display(
                        'Usage: eval-lookup JINJA_EXPRESSION [host=HOST]'
                    )
                    continue
                command_host = self._resolve_inspection_host(host_name, inspect_host)
                if command_host is None:
                    if host_name is None:
                        self._display.warning('Inspection host is unavailable')
                    continue
                command_vars = self._vars_for_inspection_host(
                    task,
                    command_host,
                    task_vars_by_host,
                )
                self._show_lookup_expression(
                    expression,
                    command_host,
                    command_vars,
                )
                continue
            if verb in ('e', 'eval'):
                try:
                    expression, host_name = self._parse_eval_command(response)
                except ValueError as exc:
                    self._display.display('Invalid eval command: %s' % to_text(exc))
                    self._display.display(
                        'Usage: eval JINJA_EXPRESSION [host=HOST]'
                    )
                    continue
                command_host = self._resolve_inspection_host(host_name, inspect_host)
                if command_host is None:
                    if host_name is None:
                        self._display.warning('Inspection host is unavailable')
                    continue
                command_vars = self._vars_for_inspection_host(
                    task,
                    command_host,
                    task_vars_by_host,
                )
                self._show_expression(expression, command_host, command_vars)
                continue
            if verb == 'watch':
                if len(parts) == 2 and parts[1].lower() == 'list':
                    self._list_watches()
                    continue
                if len(parts) == 3 and parts[1].lower() in ('delete', 'del'):
                    try:
                        watch_id = int(parts[2])
                    except ValueError:
                        self._display.display('Watch ID must be an integer')
                    else:
                        self._delete_watch(watch_id)
                    continue
                if len(parts) >= 3 and parts[1].lower() == 'add':
                    try:
                        expression, host_name = self._parse_watch_add(response)
                    except ValueError as exc:
                        self._display.display('Invalid watch command: %s' % to_text(exc))
                    else:
                        self._add_watch(expression, host_name)
                    continue
                self._display.display(
                    'Usage: watch add EXPRESSION [host=HOST] | '
                    'watch list | watch delete ID'
                )
                continue
            if verb == 'tasks':
                try:
                    task_options = self._parse_tasks_command(response)
                except ValueError as exc:
                    self._display.display('Invalid tasks command: %s' % to_text(exc))
                    self._display.display(
                        'Usage: tasks [tree] [host=HOST] [regex=REGEXP] '
                        '[role=NAME] [tag=TAG]'
                    )
                else:
                    self._show_task_catalog(task, inspect_host, task_options)
                continue
            if verb == 'break':
                if len(parts) == 2 and parts[1].lower() == 'list':
                    self._list_breakpoints()
                    continue
                if len(parts) == 3 and parts[1].lower() in ('delete', 'del'):
                    try:
                        breakpoint_id = int(parts[2])
                    except ValueError:
                        self._display.display('Breakpoint ID must be an integer')
                    else:
                        self._delete_breakpoint(breakpoint_id)
                    continue
                if len(parts) == 3 and parts[1].lower() == 'pick':
                    try:
                        task_id = int(parts[2])
                        self._add_task_catalog_breakpoint(task_id)
                    except ValueError as exc:
                        self._display.display(
                            'Invalid task breakpoint: %s' % to_text(exc)
                        )
                    continue
                if len(parts) >= 3 and parts[1].lower() in ('task', 'role', 'tag'):
                    try:
                        breakpoint_type, breakpoint_value = (
                            self._parse_breakpoint_definition(response)
                        )
                        self._add_breakpoint(breakpoint_type, breakpoint_value)
                    except ValueError as exc:
                        self._display.display(
                            'Invalid breakpoint: %s' % to_text(exc)
                        )
                    continue
                self._display.display(
                    'Usage: break pick TASK_ID | break task REGEX | break role NAME | '
                    'break tag TAG | break list | break delete ID'
                )
                continue
            if verb in ('vars', 'vars!', 'v', 'v!', 'var', 'var!'):
                try:
                    variable_selector, host_name, max_depth = self._parse_vars_options(
                        parts[1:]
                    )
                except ValueError as exc:
                    self._display.display('Invalid vars options: %s' % to_text(exc))
                    self._display.display(
                        'Usage: %s [NAME|PATH|glob=PATTERN|regex=REGEXP|JINJA_EXPRESSION] '
                        '[host=HOST] [depth=N]' % verb
                    )
                    continue
                command_host = self._resolve_inspection_host(
                    host_name,
                    inspect_host,
                )
                if command_host is None:
                    if host_name is None:
                        self._display.warning('Inspection host is unavailable')
                    continue
                command_vars = self._vars_for_inspection_host(
                    task,
                    command_host,
                    task_vars_by_host,
                )
                self._show_vars(
                    command_host,
                    command_vars,
                    variable_selector=variable_selector,
                    reveal_secrets=verb.endswith('!'),
                    max_depth=max_depth,
                    explicit_host=host_name is not None,
                )
                continue
            if verb == 'set':
                try:
                    variable_name, value, host_name = self._parse_set_command(response)
                except ValueError as exc:
                    self._display.display('Invalid set command: %s' % to_text(exc))
                    self._display.display('Usage: set NAME YAML_VALUE [host=HOST]')
                    continue
                changed_hosts = self._set_variable(
                    task,
                    variable_name,
                    value,
                    host_name,
                    task_vars_by_host,
                )
                if inspect_host is not None and inspect_host.get_name() in changed_hosts:
                    task_vars = self._vars_for_inspection_host(
                        task,
                        inspect_host,
                        task_vars_by_host,
                    )
                continue
            if command in ('a', 'args', 'args!'):
                self._show_args(task, task_vars, reveal_secrets=command.endswith('!'))
                continue

            if verb in ('template', 'template-save'):
                try:
                    command_parts = shlex.split(response)
                except ValueError as exc:
                    self._display.display(
                        'Invalid %s command: %s' % (verb, to_text(exc))
                    )
                    continue

                if verb == 'template':
                    if len(command_parts) not in (1, 2):
                        self._display.display('Usage: template [HOST]')
                        continue
                    local_path = None
                    host_name = command_parts[1] if len(command_parts) == 2 else None
                else:
                    if len(command_parts) not in (2, 3):
                        self._display.display('Usage: template-save LOCAL_PATH [HOST]')
                        continue
                    local_path = command_parts[1]
                    host_name = command_parts[2] if len(command_parts) == 3 else None

                command_host = self._resolve_inspection_host(host_name, inspect_host)
                if command_host is None:
                    if host_name is None:
                        self._display.warning('Inspection host is unavailable')
                    continue
                command_vars = self._vars_for_inspection_host(
                    task,
                    command_host,
                    task_vars_by_host,
                )
                self._inspect_template(
                    task,
                    command_host,
                    command_vars,
                    local_path=local_path,
                )
                continue

            if response:
                self._display.display("Unknown command '%s'. Type 'help' for commands." % response)
