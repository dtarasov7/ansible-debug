"""Exercise skip reasons, stdout suppression, tag selection and runtime toggling."""
import os
from pathlib import Path
import re
import subprocess
import sys

import pexpect


root = Path(__file__).resolve().parents[1]
variant = sys.argv[1]
env = dict(
    os.environ,
    ANSIBLE_STRATEGY_PLUGINS=str(root / 'strategy_plugins'),
    ANSIBLE_LOCAL_TEMP=str(root / 'tests/.local'),
    ANSIBLE_REMOTE_TEMP=str(root / 'tests/.remote'),
    ANSIBLE_NOCOLOR='1',
    # Explicit diagnostics must still work when the normal callback hides skips.
    ANSIBLE_DISPLAY_SKIPPED_HOSTS='false',
)


def run(show_tags, toggle=False):
    run_env = dict(env, ANSIBLE_INSPECT_SHOW_TAG_SKIPS=str(show_tags).lower())
    if show_tags:
        run_env['ANSIBLE_DISPLAY_SKIPPED_HOSTS'] = 'true'
    args = ['-i', 'first,second,', '-c', 'local', str(root / 'tests/skips.yml'),
            '-e', 'inspector=' + variant, '--step', '--tags', 'chosen,always',
            '--skip-tags', 'banned']
    child = pexpect.spawn('ansible-playbook', args, env=run_env, encoding='utf-8', timeout=40)
    log_path = root / ('tests/' + variant + '-skips-%s.log' % show_tags)
    with log_path.open('w', encoding='utf-8') as log:
        child.logfile_read = log
        child.expect_exact('inspect-step> ')
        initial = child.before
        assert 'skipping: [tags]' not in initial, initial
        assert 'INSPECT TASK: excluded static task' not in initial

        def command(value):
            child.sendline(value)
            child.expect_exact('inspect-step> ')
            return child.before

        if toggle:
            output = command('tag-skips on')
            assert 'skipping: [tags]' not in output, output
            assert 'Usage: tag-skips' in command('tag-skips invalid')
            assert 'Tag skips: on' in command('tag-skips')
            assert 'Tag skips: off' in command('tag-skips off')
            assert 'skipping: [tags]' not in command('tag-skips on')
        else:
            assert 'Tag skips: %s' % ('on' if show_tags else 'off') in command('tag-skips')

        output = command('r')  # first anchor -> conditional
        names = ('excluded static task', 'excluded by skip tags', 'excluded never task',
                 'excluded imported task', 'skip_static_probe : excluded static role task',
                 'excluded inherited task', 'excluded always task')
        positions = [output.index('skipping: [tags] ' + name) for name in names]
        assert positions == sorted(positions), output
        assert positions[0] > output.index('first anchor ran'), output
        assert positions[-1] < output.index('INSPECT TASK: false conditional'), output
        assert 'skipping: [tags] excluded rescue task' not in output, output
        assert '"only_tags"' in output and '"skip_tags"' in output and '"banned"' in output
        output = command('r')  # conditional -> mixed loop
        assert 'skipping: [tags]' not in output, output
        for host in ('first', 'second'):
            assert output.count('skipping: [%s] false conditional' % host) == 1, output
        assert 'Conditional result was False' in output, output
        # Some old executor versions do not return false_condition.
        if 'false_condition' in output:
            assert 'enabled' in output

        output = command('r')  # mixed loop -> empty loop
        for host in ('first', 'second'):
            assert output.count('skipping: [%s] mixed loop' % host) == 1, output
        assert '"item": "skip"' in output and "item == 'run'" in output, output

        output = command('r')  # empty loop -> protected skip
        assert 'No items in the list' in output or 'No items in list' in output, output
        output = command('r')  # protected skip -> protected loop skip
        assert 'skipping: [first] protected skip' in output and 'censored' in output, output
        assert 'private-result-marker' not in output.split('INSPECT TASK:')[0], output
        output = command('r')  # protected loop -> operator skip
        assert 'skipping: [first] protected loop skip' in output and 'censored' in output, output
        assert output.count('skipping: [first] protected loop skip') == 1, output
        assert 'private-item-marker' not in output, output
        output = command('s')
        assert 'Skipped by operator (s/skip)' in output, output
        assert 'skipping: [first] operator skip' in output, output

        if toggle:
            command('tag-skips off')
        output = command('r')  # include expansion -> included conditional
        assert ('skipping: [tags] excluded dynamic task' in output) == (not toggle), output
        assert 'skipping: [tags] excluded dynamic tail' not in output, output
        assert 'INSPECT TASK: excluded dynamic task' not in output
        if toggle:
            assert 'skipping: [tags]' not in command('tag-skips on')
        output = command('r')  # included conditional -> include_role
        assert 'skipping: [first] included conditional' in output, output
        assert output.index('skipping: [tags] excluded dynamic tail') < output.index('INSPECT TASK: dynamic role'), output
        if toggle:
            command('tag-skips off')
        output = command('r')  # role expansion -> role conditional
        assert ('skipping: [tags] skip_probe : excluded role task' in output) == (not toggle), output
        if toggle:
            output = command('tag-skips on')
            assert 'skipping: [tags]' not in output, output
        output = command('r')  # role conditional -> last anchor
        assert 'skipping: [first] skip_probe : role conditional' in output, output
        assert output.index('skipping: [tags] skip_probe : excluded role tail') < output.index('INSPECT TASK: last anchor'), output
        assert 'skipping: [tags] excluded final tail' not in output, output
        child.sendline('r')
        child.expect(pexpect.EOF)
        assert child.before.index('last anchor ran') < child.before.index('skipping: [tags] excluded final tail'), child.before
        child.close()
    assert child.exitstatus == 0, log_path.read_text()
    output = log_path.read_text()
    assert 'Traceback' not in output and 'Failure using method' not in output, output
    assert 'failed=0' in output and 'skipped=6' in output, output
    assert 'INSPECT TASK: excluded' not in output, output
    assert output.count('skipping: [tags] excluded static task') == 1, output


run(False, toggle=True)
run(True)

# Diagnostics must not change execution or recap, including outside --step.
recaps = []
for strategy, show_tags in [('linear', False), (variant, False), (variant, True)]:
    run_env = dict(env, ANSIBLE_INSPECT_SHOW_TAG_SKIPS=str(show_tags).lower())
    if show_tags:
        run_env.pop('ANSIBLE_NOCOLOR', None)
        run_env['ANSIBLE_FORCE_COLOR'] = '1'
    process = subprocess.run(
        ['ansible-playbook', '-i', 'first,second,', '-c', 'local',
         str(root / 'tests/skips.yml'), '-e', 'inspector=' + strategy,
         '--tags', 'chosen,always', '--skip-tags', 'banned,operator'],
        env=run_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8',
        timeout=60,
    )
    assert process.returncode == 0, process.stdout
    if show_tags:
        assert re.search(r'\x1b\[[0-9;]*36m', process.stdout), process.stdout
        assert 'skipping: [tags]' in process.stdout, process.stdout
    else:
        assert 'skipping: [tags]' not in process.stdout, process.stdout
    plain = re.sub(r'\x1b\[[0-9;]*m', '', process.stdout)
    recaps.append(re.findall(r'^(?:first|second)\s+:.*$', plain, re.MULTILINE))
assert recaps[0] == recaps[1] == recaps[2] and len(recaps[0]) == 2, recaps
print(variant + ': skip integration PASS')
