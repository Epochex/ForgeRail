import json

import pytest


def test_cache_key_tracks_dependency_contents_and_ignores_mapping_order(tmp_path):
    from gamebuild.cache import ContentCache
    cache = ContentCache(tmp_path / "cache")
    dependency = tmp_path / "texture.bin"
    dependency.write_bytes(b"first")
    first = cache.key({"target": "windows", "dependencies": [dependency]})
    assert first == cache.key({"dependencies": [dependency], "target": "windows"})
    dependency.write_bytes(b"other")
    assert cache.key({"target": "windows", "dependencies": [dependency]}) != first
    assert cache.key({"target": "android", "dependencies": [dependency]}) != first


def test_cache_restores_verified_directory_and_never_overwrites_entry(tmp_path):
    from gamebuild.cache import ContentCache
    cache = ContentCache(tmp_path / "cache")
    source = tmp_path / "export"
    source.mkdir()
    (source / "bundle").write_bytes(b"asset bundle")
    key = cache.key({"engine": "6000.3", "rules": "v1"})
    cache.put(key, source)
    assert cache.get(key, tmp_path / "restored") is True
    assert (tmp_path / "restored/bundle").read_bytes() == b"asset bundle"
    cache.put(key, source)
    (source / "bundle").write_bytes(b"changed")
    with pytest.raises(ValueError, match="immutable"):
        cache.put(key, source)


@pytest.mark.parametrize("corruption", ["content", "extra", "manifest"])
def test_cache_corruption_becomes_miss_without_partial_destination(tmp_path, corruption):
    from gamebuild.cache import ContentCache
    cache = ContentCache(tmp_path / "cache")
    source = tmp_path / "source"
    source.mkdir()
    (source / "bundle").write_bytes(b"good")
    key = cache.key({"rules": "v1"})
    cache.put(key, source)
    entry = tmp_path / "cache" / key
    if corruption == "manifest":
        (entry / "manifest.json").write_text('{"files": [{"path": "../../escape"}]}')
    elif corruption == "extra":
        (entry / "data/extra").write_bytes(b"unlisted")
    else:
        (entry / "data/bundle").write_bytes(b"bad")
    assert cache.get(key, tmp_path / "destination") is False
    assert not (tmp_path / "destination").exists()
    assert not entry.exists()
    assert list((tmp_path / "cache/quarantine").iterdir())


@pytest.mark.parametrize("key", ["../escape", "", "A" * 64, "/absolute", "x\\..\\escape"])
def test_malicious_cache_key_is_rejected_without_writing(tmp_path, key):
    from gamebuild.cache import ContentCache
    cache = ContentCache(tmp_path / "cache")
    with pytest.raises(ValueError):
        cache.get(key, tmp_path / "output")
    with pytest.raises(ValueError):
        cache.put(key, tmp_path / "missing")


def test_cache_restore_preserves_existing_destination(tmp_path):
    from gamebuild.cache import ContentCache
    cache = ContentCache(tmp_path / "cache")
    source = tmp_path / "one.bin"
    source.write_bytes(b"one")
    key = cache.key({"input": "one"})
    cache.put(key, source)
    destination = tmp_path / "output.bin"
    destination.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        cache.get(key, destination)
    assert destination.read_bytes() == b"keep"


def test_cache_rejects_source_and_destination_that_mutate_its_own_root(tmp_path):
    from gamebuild.cache import ContentCache
    cache = ContentCache(tmp_path / "cache")
    source = tmp_path / "source.bin"
    source.write_bytes(b"safe")
    key = cache.key({"input": "safe"})
    cache.put(key, source)
    with pytest.raises(ValueError, match="cache root"):
        cache.get(key, cache.root / key / "unexpected")
    # Copying a parent containing the cache would recursively copy its staging dir.
    with pytest.raises(ValueError, match="cache root"):
        cache.put(cache.key({"parent": True}), tmp_path)


def test_cache_rejects_symbolic_link_sources(tmp_path):
    from gamebuild.cache import ContentCache
    source = tmp_path / "real.bin"
    source.write_bytes(b"real")
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("host does not grant symbolic-link creation")
    cache = ContentCache(tmp_path / "cache")
    with pytest.raises(ValueError, match="link"):
        cache.put(cache.key({"input": "link"}), link)
