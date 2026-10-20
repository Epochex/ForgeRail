"""Local node launcher: credentials stay in the ignored file/environment."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
credentials=json.loads((ROOT/'.runtime/credentials.json').read_text(encoding='utf-8-sig'))
os.environ['GAMEBUILD_TOKEN']=credentials['token']
os.chdir(ROOT)
sys.argv=['gamebuild','worker','--url','http://127.0.0.1:18981','--name','windows-unity',
          '--root',str(ROOT/'runtime/windows-ci-node'),'--projects',json.dumps({'buildlab':str(ROOT)}),
          '--unity',str(ROOT/'runtime/tools/unity/6000.3.0f1/Editor/Unity.exe')]
from gamebuild.cli import main
main()
