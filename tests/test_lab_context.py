import sys
import pytest
from gamebuild.lab.context import Context


def test_context_captures_actual_command_and_rejects_escape(tmp_path):
    events = []
    ctx = Context(tmp_path, '01', 'default', 'execute', emit=lambda e: events.append(e))
    ctx.write('config.json', {'value': 3})
    result = ctx.command([sys.executable, '-c', 'print(7)'])
    assert result['exit_code'] == 0 and '7' in result['stdout']
    assert events and any(e.get('data', {}).get('exit_code') == 0 for e in events)
    with pytest.raises(ValueError):
        ctx.write('../escape.json', {})


def test_context_result_uses_assertions_not_a_preset_status(tmp_path):
    ctx = Context(tmp_path, '01', 'default', 'verify')
    assert ctx.result('checked', [ctx.check('bytes', False, 'good', 'bad')])['passed'] is False
    assert ctx.result('checked', [ctx.check('bytes', True, 'good', 'good')])['execution_mode'] == 'lab'


def test_python_command_preserves_chinese_output(tmp_path):
    ctx = Context(tmp_path, '01', 'default', 'execute')
    result = ctx.command([sys.executable, '-c', 'print("构建资源检查")'])
    assert result['stdout'].strip() == '构建资源检查'
