"""Check trust, nested lookup blocking and restoration on modern engines."""
import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock, patch

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader, lookup_loader
from ansible.release import __version__

init_plugin_loader()
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inspector', root / ('strategy_plugins/' + sys.argv[1] + '.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
strategy = module.StrategyModule.__new__(module.StrategyModule)
strategy._loader = DataLoader()
strategy._display = Mock()
strategy._check_ansible_version()
for version in ('2.13.13', '2.22.0', 'unknown'):
    with patch.object(module, 'ANSIBLE_VERSION', version):
        try:
            strategy._check_ansible_version()
        except module.AnsibleError:
            pass
        else:
            raise AssertionError('version gate accepted ' + version)

original_get = lookup_loader.get
for expression in ("{{ lookup('env', 'PATH') }}", "{{ query('env', 'PATH') }}", "{{ q('env', 'PATH') }}"):
    ok, result = strategy._evaluate_expression(expression, {})
    assert not ok and 'disabled' in result, (ok, result)
    assert lookup_loader.get == original_get
    ok, result = strategy._evaluate_expression(expression, {}, disable_lookups=False)
    assert ok and result, (ok, result)

if tuple(map(int, __version__.split('.')[:2])) >= (2, 19):
    from ansible.template import trust_as_template
    nested = trust_as_template("{{ lookup('env', 'PATH') }}")
    ok, result = strategy._evaluate_expression('{{ nested }}', {'nested': nested})
    assert not ok and 'disabled' in result, (ok, result)
    # Trust only the operator expression, never arbitrary variable content.
    ok, result = strategy._evaluate_expression('{{ nested }}', {'nested': '{{ 6 * 7 }}'})
    assert ok and result == '{{ 6 * 7 }}', (ok, result)
assert lookup_loader.get == original_get
print(sys.argv[1] + ': expression and version-gate checks PASS')
