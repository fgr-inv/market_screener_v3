"""Fast release-contract checks used by CI before the full test suite."""
from __future__ import annotations

from pathlib import Path
import ast
import re


ROOT=Path(__file__).resolve().parents[1]
RESEARCH_FILES=(
    ROOT/'core'/'signal_lab.py',ROOT/'core'/'opportunity_lifecycle.py',
    ROOT/'core'/'regime_multitimeframe.py',ROOT/'core'/'factor_risk.py',
    ROOT/'scripts'/'run_opportunity_lifecycle.py',
)


def main():
    failures=[]
    version=(ROOT/'core'/'config.py').read_text(encoding='utf-8')
    if 'APP_VERSION = "11.39.9"' not in version: failures.append('APP_VERSION is not 11.39.9')
    combined=''
    for path in RESEARCH_FILES:
        source=path.read_text(encoding='utf-8'); combined+=source.lower()+'\n'
        try: ast.parse(source,filename=str(path))
        except SyntaxError as exc: failures.append(f'{path.name}: {exc}')
        if re.search(r'\.shift\(\s*-\d',source): failures.append(f'{path.name}: future shift detected')
    for forbidden in ('place_order','submit_order','tradingclient','alpaca_trade_api'):
        if forbidden in combined: failures.append(f'broker/order boundary violated: {forbidden}')
    workflows=list((ROOT/'.github'/'workflows').glob('*.yml'))
    for path in workflows:
        text=path.read_text(encoding='utf-8')
        if not text.strip().startswith('name:') or '\njobs:' not in text:
            failures.append(f'{path.name}: malformed workflow shell')
    if failures:
        print('QUALITY GATE FAILED\n- '+'\n- '.join(failures)); return 1
    print(f'Quality gate passed: {len(RESEARCH_FILES)} research modules, {len(workflows)} workflows, Shadow Mode boundary intact.')
    return 0


if __name__=='__main__': raise SystemExit(main())
