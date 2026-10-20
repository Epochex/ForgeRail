from pathlib import Path


def asset(root, name, guid="1" * 32, content="x"):
    path = root / "Assets" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.with_name(path.name + ".meta").write_text(f"fileFormatVersion: 2\nguid: {guid}\n")
    return path


def test_valid_assets_have_no_issues(tmp_path):
    from gamebuild.checks import check_assets
    asset(tmp_path, "config.json", content='{"speed": 3}')
    assert check_assets(tmp_path) == {"passed": True, "issues": []}


def test_missing_file_and_directory_metadata_block_build(tmp_path):
    from gamebuild.checks import check_assets
    path = asset(tmp_path, "Textures/pixel.txt")
    path.with_name(path.name + ".meta").unlink()
    issues = check_assets(tmp_path)["issues"]
    assert {i["path"] for i in issues if i["rule_id"] == "missing_meta"} == {
        "Assets/Textures", "Assets/Textures/pixel.txt"
    }


def test_duplicate_and_invalid_guids_are_reported(tmp_path):
    from gamebuild.checks import check_assets
    asset(tmp_path, "a.txt")
    asset(tmp_path, "b.txt")
    asset(tmp_path, "c.txt", guid="bad")
    rules = {i["rule_id"] for i in check_assets(tmp_path)["issues"]}
    assert {"duplicate_guid", "invalid_guid"} <= rules


def test_case_conflict_is_portably_detected_from_orphan_meta(tmp_path):
    from gamebuild.checks import check_assets
    path = asset(tmp_path, "Case.txt")
    # Rename through a temporary name so NTFS preserves the conflicting case.
    meta = path.with_name(path.name + ".meta")
    temporary = meta.rename(meta.with_name("temporary.meta"))
    temporary.rename(meta.with_name("case.TXT.meta"))
    assert "case_conflict" in {i["rule_id"] for i in check_assets(tmp_path)["issues"]}


def test_size_invalid_json_and_sensitive_files_fail(tmp_path):
    from gamebuild.checks import check_assets
    asset(tmp_path, "large.bin", content="12345")
    asset(tmp_path, "config.json", guid="2" * 32, content="{broken")
    asset(tmp_path, ".env", guid="3" * 32)
    rules = {i["rule_id"] for i in check_assets(tmp_path, max_asset_bytes=4)["issues"]}
    assert {"asset_too_large", "invalid_json", "forbidden_path"} <= rules


def test_environment_report_does_not_claim_unchecked_unity_license(tmp_path, monkeypatch):
    from gamebuild.checks import environment_report
    monkeypatch.chdir(tmp_path)
    report = environment_report(tmp_path / "missing-unity.exe")
    assert report["python"]
    assert report["disk_free_bytes"] > 0
    assert report["workspace_writable"] is True
    assert report["unity"]["available"] is False
    assert report["unity"]["license"] == "not_checked"
