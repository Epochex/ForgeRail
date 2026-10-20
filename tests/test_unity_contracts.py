"""Executable .NET contract tests; these never claim Unity compilation coverage."""
from pathlib import Path
import shutil
import subprocess
import json
import os
import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_unity_request_and_smoke_identity_contracts(tmp_path):
    if not shutil.which("dotnet"):
        pytest.skip(".NET SDK unavailable; Unity integration is separately gated")
    result = subprocess.run(
        ["dotnet", "run", "--project", str(ROOT / "tests/unity_contracts/UnityContracts.csproj"), "--configuration", "Release",
         f"-p:BaseIntermediateOutputPath={tmp_path}/obj/", f"-p:OutputPath={tmp_path}/bin/"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        env={**os.environ, "DOTNET_CLI_UI_LANGUAGE": "en"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS 22 executable C# contract checks" in result.stdout

@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell entrypoint")
def test_unity_wrapper_reports_missing_editor_without_faking_a_build(tmp_path):
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    evidence = tmp_path / "evidence"
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(ROOT / "scripts/build-unity.ps1"), "-Request", str(request),
        "-UnityPath", str(tmp_path / "missing-editor.exe"), "-ReportsDirectory", str(evidence),
    ], capture_output=True, timeout=30)
    assert result.returncode == 2
    report = json.loads((evidence / "invocation.json").read_text(encoding="utf-8-sig"))
    assert report["status"] == "blocked"
    assert "Unity Editor missing" in report["error"]
    assert not (tmp_path / "player").exists()

@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell entrypoint")
def test_wrapper_decodes_utf8_request_before_reporting_wrong_executable(tmp_path):
    request=tmp_path / "request.json"
    request.write_text(json.dumps({"output_dir": str(tmp_path / "中文构建" / "output")},ensure_ascii=False),encoding="utf-8")
    evidence=tmp_path / "evidence"
    result=subprocess.run([
        "powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(ROOT / "scripts/build-unity.ps1"),
        "-Request",str(request),"-UnityPath",str(Path(os.environ["SystemRoot"]) / "System32/whoami.exe"),"-ReportsDirectory",str(evidence),"-TimeoutSeconds","5",
    ],capture_output=True,timeout=20)
    report=json.loads((evidence / "invocation.json").read_text(encoding="utf-8-sig"))
    assert "editor_exit_code" in report, report
    assert result.returncode == 1
    assert report["status"] == "failed"

def test_scripts_compile_against_official_unity_api_references_when_installed(tmp_path):
    editor = Path(os.environ.get("UNITY_EDITOR_PATH", ROOT / "runtime/tools/unity/6000.3.0f1/Editor/Unity.exe"))
    managed = editor.parent / "Data/Managed"
    if not shutil.which("dotnet") or not (managed / "UnityEngine/UnityEngine.CoreModule.dll").is_file():
        pytest.skip("Official Unity reference assemblies unavailable; this check is not engine acceptance")
    result = subprocess.run([
        "dotnet", "build", str(ROOT / "tests/unity_api_compile/UnityApiCompile.csproj"),
        "--configuration", "Release", f"-p:UnityManagedPath={managed}",
        f"-p:BaseIntermediateOutputPath={tmp_path}/obj/", f"-p:OutputPath={tmp_path}/bin/",
    ], capture_output=True, encoding="utf-8", errors="replace", timeout=120,
       env={**os.environ, "DOTNET_CLI_UI_LANGUAGE": "en"})
    assert result.returncode == 0, result.stdout + result.stderr
