"""Closed set of local Lab mechanisms with one public execution contract."""
from . import assets, source, builds, systems

_MODULES = {**dict.fromkeys(('01','02','15'), assets),
            **dict.fromkeys(('03','04'), source),
            **dict.fromkeys(('05','06','13','14'), builds),
            **dict.fromkeys(('07','08','09','10','11','12','16'), systems)}


def _dispatch(ctx, action):
    if ctx.case_id not in _MODULES:
        raise ValueError('unknown Lab case')
    with ctx.stage({'prepare':'准备实验', 'inject':'制造故障', 'execute':'执行验证', 'repair':'应用修复'}[action]):
        return getattr(_MODULES[ctx.case_id], action)(ctx)


def prepare(ctx): return _dispatch(ctx, 'prepare')
def inject(ctx): return _dispatch(ctx, 'inject')
def execute(ctx):
    from .expectations import recognizes
    result = _dispatch(ctx, 'execute')
    result['fault_signature'] = {'case':ctx.case_id,'variant':ctx.variant,
                                 'observed':bool(not result['passed'] and recognizes(ctx.case_id,ctx.variant,result))}
    return result
def repair(ctx): return _dispatch(ctx, 'repair')
