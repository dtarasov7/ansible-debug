"""Check tag exclusion timing across branches, early exits and start-at-task."""
import os
from pathlib import Path
import re
import subprocess
import sys


root = Path(__file__).resolve().parents[1]
variant = sys.argv[1]
env = dict(os.environ, ANSIBLE_STRATEGY_PLUGINS=str(root / 'strategy_plugins'),
           ANSIBLE_LOCAL_TEMP=str(root / 'tests/.local'), ANSIBLE_NOCOLOR='1')


def run(strategy, mode, start=False):
    args = ['ansible-playbook', '-i', 'first,second,', '-c', 'local',
            str(root / 'tests/tag-order.yml'), '-e', 'inspector=' + strategy,
            '-e', 'order_mode=' + mode, '--tags', 'chosen']
    if start:
        args += ['--start-at-task', 'branch success']
    process = subprocess.run(args, env=dict(env, ANSIBLE_INSPECT_SHOW_TAG_SKIPS='true'),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             encoding='utf-8', timeout=60)
    assert process.returncode == (2 if mode == 'fatal' else 0), process.stdout
    return process.stdout


for mode, start in [('normal', False), ('rescue', False), ('end', False),
                    ('fatal', False), ('normal', True), ('split', False)]:
    baseline = run('linear', mode, start)
    output = run(variant, mode, start)
    (root / ('tests/' + variant + '-order-%s-%s.log' % (mode, start))).write_text(output, encoding='utf-8')
    recap = r'^(?:first|second)\s+:.*$'
    assert re.findall(recap, output, re.MULTILINE) == re.findall(recap, baseline, re.MULTILINE), output
    if start:
        assert 'skipping: [tags] excluded before block' not in output, output
        assert 'skipping: [tags] abandoned regular' not in output, output
    else:
        assert output.index('order first ran') < output.index('skipping: [tags] excluded before block'), output
    if mode == 'fatal':
        assert 'skipping: [tags] always prefix' not in output, output
        assert 'skipping: [tags] excluded trailing' not in output, output
        continue
    if mode in ('rescue', 'split'):
        if mode == 'rescue':
            assert 'skipping: [tags] abandoned regular' not in output, output
            assert 'skipping: [tags] regular tail' not in output, output
        else:
            assert output.index('branch success ran') < output.index('skipping: [tags] regular tail'), output
        assert output.index('intentional rescued failure') < output.index('skipping: [tags] rescue prefix'), output
        assert output.index('rescue anchor ran') < output.index('skipping: [tags] rescue tail'), output
        assert output.index('skipping: [tags] rescue tail') < output.index('skipping: [tags] always prefix'), output
    else:
        assert 'skipping: [tags] rescue prefix' not in output, output
        assert 'skipping: [tags] rescue tail' not in output, output
    assert output.index('always anchor ran') < output.index('skipping: [tags] always tail'), output
    if mode == 'end':
        assert 'skipping: [tags] excluded after stop' not in output, output
        assert 'skipping: [tags] excluded trailing' not in output, output
    else:
        assert output.index('skipping: [tags] excluded after stop') < output.index('after stop anchor ran'), output
        assert output.index('after stop anchor ran') < output.index('skipping: [tags] excluded trailing'), output
        if not start:
            assert output.index('skipping: [tags] excluded trailing') < output.index('final handler ran'), output

print(variant + ': tag order integration PASS')
