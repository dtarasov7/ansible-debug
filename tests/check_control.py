"""Check skip, include run-all, handler stops, no_log override and set."""
import os
from pathlib import Path
import sys
import pexpect

root = Path(__file__).resolve().parents[1]
variant = sys.argv[1]
env = dict(os.environ, ANSIBLE_STRATEGY_PLUGINS=str(root / 'strategy_plugins'),
           ANSIBLE_LOCAL_TEMP=str(root / 'tests/.local'), ANSIBLE_NOCOLOR='1')
child = pexpect.spawn('ansible-playbook', ['-i', 'first,second,', '-c', 'local',
    str(root / 'tests/control.yml'), '-e', 'inspector=' + variant, '--step'],
    env=env, encoding='utf-8', timeout=30)
with open(root / ('tests/' + variant + '-control.log'), 'w', encoding='utf-8') as log:
    child.logfile_read = log
    child.expect_exact('inspect-step> ')
    child.sendline('s')
    child.expect_exact('INSPECT TASK: include probe')
    child.expect_exact('inspect-step> ')
    child.sendline('ra')
    child.expect_exact('inspect-step> ')
    assert 'INSPECT TASK: no log probe' in child.before, child.before
    assert 'included handler ran' in child.before
    child.sendline('r!')
    child.expect_exact('revealed by operator')
    child.expect_exact('inspect-step> ')
    child.sendline('set inspector_value 73')
    child.expect_exact('inspect-step> ')
    child.sendline('r')
    child.expect_exact('inspect-step> ')
    child.sendline('c')
    child.expect(pexpect.EOF)
    child.close()
assert child.exitstatus == 0, child.exitstatus
print(variant + ': control integration PASS')
