"""Make public evidence copies without exposing runtime credentials or host roots."""
import json
from pathlib import Path
import re
from gamebuild.diagnostics import _redact

PRIVATE = re.compile(r'(?i)(?:^|_)(?:token|password|secret|authorization|credentials?|api_?key)(?:$|_)')


def clean(value, roots=()):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if PRIVATE.search(k) else clean(v,roots) for k,v in value.items()}
    if isinstance(value, list): return [clean(v,roots) for v in value]
    if isinstance(value, str):
        for root in roots:
            for text in (str(root), Path(root).as_posix()):
                value=value.replace(text,'[lab]').replace(json.dumps(text)[1:-1],'[lab]')
        value=_redact(value)
        return re.sub(r'(?i)("(?:[a-z_]*token|password|secret|authorization|credentials?|api_?key)"\s*:\s*)"[^"\n]*"',
                      r'\1"[REDACTED]"',value)
    return value


def clean_text(text, roots=()):
    try: return json.dumps(clean(json.loads(text),roots),ensure_ascii=False,indent=2)
    except (ValueError,TypeError):
        return '\n'.join(clean(line,roots) for line in text.split('\n'))
