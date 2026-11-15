"""T016."""

import pytest

from analogfinder import storage


def test_fingerprint_key_order_and_values():
    assert storage.fingerprint({"a": 1, "b": [1.5, "x"]}) == storage.fingerprint(
        {"b": [1.5, "x"], "a": 1}
    )
    assert storage.fingerprint({"a": 1}) != storage.fingerprint({"a": 2})
    assert storage.fingerprint({"a": 1}) != storage.fingerprint({"a": 1.0})
    assert len(storage.fingerprint({})) == 16


def test_canonical_json_is_plain_json():
    assert storage.canonical_json({"b": [0.1, 2], "a": "é"}) == '{"a":"é","b":[0.1,2]}'
    with pytest.raises(ValueError):
        storage.canonical_json({"x": float("nan")})


def test_atomic_dir_exception_leaves_nothing_complete(tmp_path):
    final = tmp_path / "x"
    with pytest.raises(RuntimeError):
        with storage.atomic_dir(final) as d:
            (d / "f").write_text("1")
            raise RuntimeError
    assert not final.exists() and not storage.is_complete(final)
    assert list(tmp_path.glob("x.partial-*"))


def test_atomic_dir_success_and_no_overwrite(tmp_path):
    final = tmp_path / "x"
    with storage.atomic_dir(final, manifest={"k": 1}) as d:
        (d / "f").write_text("1")
    assert storage.is_complete(final) and (final / "f").read_text() == "1"
    with pytest.raises(FileExistsError):
        with storage.atomic_dir(final):
            pass


def test_cache_dir_stable(tmp_path):
    a = storage.cache_dir(tmp_path, "s", "1", {"bbox": [1, 2, 3, 4]})
    b = storage.cache_dir(tmp_path, "s", "1", {"bbox": [1, 2, 3, 4]})
    assert a == b and a.parent == tmp_path / "cache" / "s" / "1"
