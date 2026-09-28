"""Regenerate standalone variants from the unchanged 2.12-2.13 implementation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'strategy_plugins/inspect_step.py').read_text(encoding='utf-8')


def replace_method(text, name, body):
    start = text.index('    def ' + name + '(')
    end = text.find('\n    def ', start + 1)
    return text[:start] + body.rstrip() + '\n' + text[end:]


source = source.replace('from ansible.module_utils._text import', 'from ansible.module_utils.common.text.converters import')
modern = source.replace('2.12-2.13', '2.14-2.18').replace('2.13.13', '2.18.19')
modern = modern.replace('MINIMUM_ANSIBLE_VERSION = (2, 12)', 'MINIMUM_ANSIBLE_VERSION = (2, 14)').replace('MAXIMUM_ANSIBLE_VERSION = (2, 14)', 'MAXIMUM_ANSIBLE_VERSION = (2, 19)')
modern = modern.replace('templar.template(label, cache=False)', 'templar.template(label)')
modern = modern.replace('name: inspect_step\n', 'name: inspect_step_2_14\n')
modern = replace_method(modern, '_check_ansible_version', '''    def _check_ansible_version(self):
        """Reject releases outside this standalone implementation's API range."""
        version = _ansible_major_minor(ANSIBLE_VERSION)
        if version is None or not MINIMUM_ANSIBLE_VERSION <= version < MAXIMUM_ANSIBLE_VERSION:
            raise AnsibleError(
                'This inspect_step variant requires ansible-core 2.14-2.18; detected %s.'
                % ANSIBLE_VERSION
            )
        self._display.display('Ansible compatibility: ansible-core %s (2.14-2.18)' % ANSIBLE_VERSION)
''')
modern = modern.replace(', do_handlers=False):', '):').replace('            do_handlers=do_handlers,\n', '').replace('if not do_handlers and self._inspect_failure_prompt_enabled:', 'if self._inspect_failure_prompt_enabled:')
start = modern.index('    def _do_handler_run(')
end = modern.index('    def _hosts_for_task(', start)
modern = modern[:start] + modern[end:]
# Handlers are part of the normal iterator starting in 2.14.
modern = modern.replace('from ansible.playbook.block import Block', 'from ansible.playbook.block import Block\nfrom ansible.playbook.handler import Handler')
modern = modern.replace('        if self._inspect_run_all_include is not None:\n            include_scope', '        if isinstance(task, Handler) and self._inspect_run_all_flushing_handlers:\n            return True\n        if self._inspect_run_all_include is not None:\n            include_scope')
# flush_handlers now schedules handlers; its return does not end their execution.
modern = modern.replace('            self._inspect_run_all_flushing_handlers = False', '            self._inspect_run_all_flushing_handlers = run_all_flush')
modern = modern.replace('        hosts_by_task = {}', '        if any(task is not None and not isinstance(task, Handler) for _, task in host_tasks):\n            self._inspect_run_all_flushing_handlers = False\n        hosts_by_task = {}')
modern = modern.replace('                loader=self._loader,\n                fail_on_undefined=', '                fail_on_undefined=')
modern = modern.replace('            do_handlers (bool): Whether handler results are being processed. /\n                Обрабатываются ли results handlers.\n', '')
modern = modern.replace('            AnsibleError: ansible-core 2.14 or newer uses incompatible internal APIs. /\n                ansible-core 2.14+ использует несовместимые внутренние API.', '            AnsibleError: Installed ansible-core is outside the supported range.')
(ROOT / 'strategy_plugins/inspect_step_2_14.py').write_text(modern, encoding='utf-8')

latest = modern.replace('2.14-2.18', '2.19-2.20').replace('2.18.19', '2.19.13').replace('name: inspect_step_2_14\n', 'name: inspect_step_2_19\n')
latest = latest.replace('MINIMUM_ANSIBLE_VERSION = (2, 14)', 'MINIMUM_ANSIBLE_VERSION = (2, 19)').replace('MAXIMUM_ANSIBLE_VERSION = (2, 19)', 'MAXIMUM_ANSIBLE_VERSION = (2, 21)')
latest = latest.replace('from ansible.template import AnsibleEnvironment, Templar, generate_ansible_template_vars', 'from ansible.template import Templar, trust_as_template\nfrom ansible._internal._templating._template_vars import generate_ansible_template_vars\nfrom unittest.mock import patch')
latest = latest.replace('            evaluator = Conditional(loader=self._loader)\n            evaluator.when = [condition]\n', '')
latest = latest.replace('matched = bool(evaluator.evaluate_conditional(templar, task_vars))', 'matched = templar.evaluate_conditional(condition)')
latest = latest.replace('from ansible.playbook.conditional import Conditional\n', '').replace('from ansible.utils.listify import listify_lookup_plugin_terms\n', '').replace('from ansible.utils.unsafe_proxy import wrap_var\n', '')
latest = latest.replace('task_result._task', 'task_result.task').replace('task_result._host', 'task_result.host').replace('task_result._result', 'task_result._return_data')
latest = latest.replace('                expression,\n                fail_on_undefined=True,\n                disable_lookups=disable_lookups,', '                trust_as_template(expression),\n                fail_on_undefined=True,')
# The old disable_lookups argument is ignored in 2.19+. Block loading throughout
# this synchronous evaluation, including nested templates/hostvars, and restore it.
latest = latest.replace('            value = templar.template(\n                trust_as_template(expression),\n                fail_on_undefined=True,\n            )', '''            if disable_lookups:
                with patch.object(lookup_loader, 'get', side_effect=AnsibleError(
                    'Lookups are disabled for this inspection command; use eval-lookup.'
                )):
                    value = templar.template(trust_as_template(expression))
            else:
                value = templar.template(trust_as_template(expression))''')
latest = latest.replace("            template_vars.update(\n                generate_ansible_template_vars(source_name, source_path, destination)\n            )", "            template_vars.update(\n                generate_ansible_template_vars(\n                    source_name, source_path, destination,\n                    include_ansible_managed='ansible_managed' not in template_vars,\n                )\n            )")
a = latest.index('            template_templar = templar.copy_with_new_env(')
b = latest.index('        finally:', a)
latest = latest[:a] + '''            overrides = {
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
''' + latest[b:]
# Match the new executor's lookup path (trust, lazy values and first_found).
a = latest.index('            fail_on_undefined = task.loop_with')
b = latest.index('\n        else:\n            items = templar.template(task.loop)', a)
latest = latest[:a] + """            from ansible._internal._templating._jinja_plugins import _invoke_lookup, _DirectCall

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
""" + latest[b:]
latest = latest.replace('from ansible.executor.module_common import get_action_args_with_defaults', 'from ansible.executor.module_common import _apply_action_arg_defaults')
a = latest.index('        templated_args = get_action_args_with_defaults(')
b = latest.index("        source_name =", a)
latest = latest[:a] + """        templated_args = _apply_action_arg_defaults(
            task.resolved_action or task.action, task, templated_args, templar,
        )
""" + latest[b:]
(ROOT / 'strategy_plugins/inspect_step_2_19.py').write_text(latest, encoding='utf-8')

# 2.21 replaces raw task results with HostTaskResult + UnifiedTaskResult.
newest = latest.replace('2.19-2.20', '2.21').replace('2.19.13', '2.21.4').replace('name: inspect_step_2_19\n', 'name: inspect_step_2_21\n')
newest = newest.replace('MINIMUM_ANSIBLE_VERSION = (2, 19)', 'MINIMUM_ANSIBLE_VERSION = (2, 21)').replace('MAXIMUM_ANSIBLE_VERSION = (2, 21)', 'MAXIMUM_ANSIBLE_VERSION = (2, 22)')
for flag in ('failed', 'changed', 'skipped', 'unreachable'):
    newest = newest.replace('task_result.is_%s()' % flag, 'task_result.utr.%s' % flag)
newest = newest.replace('task_result._return_data', 'task_result.utr.as_result_dict()')
newest = newest.replace('task.ignore_errors or not iterator.is_failed(host)', 'task_result.utr.ignore_errors or not iterator.is_failed(host)')
newest = newest.replace("if task.ignore_errors or recovery in", "if task_result.utr.ignore_errors or recovery in")
(ROOT / 'strategy_plugins/inspect_step_2_21.py').write_text(newest, encoding='utf-8')
