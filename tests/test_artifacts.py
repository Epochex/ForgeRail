import hashlib
import json
import zipfile

import pytest

from gamebuild.artifacts import make_package, verify_package


def test_package_roundtrip_and_tampering(tmp_path):
    p = tmp_path / "payload"; p.mkdir()
    (p / "file.txt").write_text("hello")
    z = tmp_path / "out.zip"
    m = make_package(p, z, {"build_id": "one"})
    assert verify_package(z, m)["files"][0]["path"] == "file.txt"
    z.write_bytes(z.read_bytes() + b"tampered")
    with pytest.raises(ValueError): verify_package(z, m)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/windows", "a\\b", "a/../../x",'CON','dir/NUL.txt','dir/trailing.','NODE_MODULES/a','dir/.env.production'])
def test_zip_traversal_rejected_even_with_correct_outer_checksum(tmp_path, name):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f: f.writestr(name, "bad")
    m = {"sha256": hashlib.sha256(z.read_bytes()).hexdigest(), "size": z.stat().st_size,
         "files": [{"path": name, "size": 3, "sha256": hashlib.sha256(b"bad").hexdigest()}]}
    with pytest.raises(ValueError): verify_package(z, m)


def test_forbidden_files_and_symlinks_are_not_packaged(tmp_path):
    p = tmp_path / "payload"; p.mkdir()
    (p / ".env").write_text("private")
    with pytest.raises(ValueError): make_package(p, tmp_path / "bad.zip", {})


def test_manifest_file_hash_must_match_payload(tmp_path):
    p = tmp_path / "payload"; p.mkdir(); (p / "a").write_text("a")
    z = tmp_path / "a.zip"; m = make_package(p, z, {})
    m["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError): verify_package(z, m)
