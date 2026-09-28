"""Exercise actual strategy hooks through an interactive local playbook."""
import os
from pathlib import Path
import sys
import pexpect

root = Path(__file__).resolve().parents[1]
variant = sys.argv[1]
env = dict(os.environ, ANSIBLE_STRATEGY_PLUGINS=str(root / 'strategy_plugins'),
           ANSIBLE_LOCAL_TEMP=str(root / 'tests/.local'),
           ANSIBLE_REMOTE_TEMP=str(root / 'tests/.remote'), ANSIBLE_NOCOLOR='1')
child = pexpect.spawn('ansible-playbook', ['-i', 'first,second,', '-c', 'local',
    str(root / 'tests/compat.yml'), '-e', 'inspector=' + variant, '--step'] + sys.argv[2:],
    env=env, encoding='utf-8', timeout=40)
log = open(root / ('tests/' + variant + '.log'), 'w', encoding='utf-8')
child.logfile_read = log

def command(value, expected=None):
    child.sendline(value)
    if expected:
        child.expect_exact(expected)
    child.expect_exact('inspect-step> ')

child.expect_exact('inspect-step> ')
command('eval {{ answer + 1 }}', '43')
command('vars answer', '42')
command('args', '42')
command('watch add {{ answer + 1 }}')
command("eval {{ lookup('env', 'PATH') }}", 'disabled')
command("eval-lookup {{ lookup('env', 'PATH') }}", '/bin')
child.sendline('r')
child.expect_exact('inspect-step> ')
command('result all', '42')
command('loop all', 'label-two')
command('loop when 2', 'RUN')
command('loop args 2', 'two')
command('loop eval 2 {{ item }}', 'two')
child.sendline('r')
child.expect_exact('inspect-step> ')
command('loop all', 'three')
child.sendline('r')
child.expect_exact('inspect-step> ')
command('template', 'answer=42')
child.sendline('r')
child.expect_exact('inspect-step> ')
child.sendline('r')
child.expect_exact('inspect-failure> ')
child.sendline('i')
child.expect_exact('inspect-step> ')
command('result all', 'ignored')
child.sendline('r')
child.expect_exact('inspect-step> ')
child.sendline('r')
child.expect_exact('INSPECT TASK: handler probe')
child.expect_exact('inspect-step> ')
child.sendline('r')
child.expect_exact('INSPECT TASK: end probe')
child.expect_exact('inspect-step> ')
child.sendline('r')
child.expect(pexpect.EOF)
child.close()
log.close()
assert child.exitstatus == 0, child.exitstatus
output = (root / ('tests/' + variant + '.log')).read_text()
assert 'failed=0' in output
assert 'Traceback' not in output
assert '<label error:' not in output
assert 'PREVIEW [first]: ERROR' not in output
print(variant + ': interactive integration PASS')
