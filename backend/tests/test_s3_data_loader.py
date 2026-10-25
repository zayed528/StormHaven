from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.core.data_loader as data_loader


def _artifact_bytes(name: str) -> bytes:
    if name == "nodes.csv":
        return b"node_id,kind,circuit_id,lat,lon,fail_prob,n_events_observed\nN-1,substation,C-1,1,2,0.1,1\n"
    if name == "edges.csv":
        return b"parent_id,child_id\nN-1,N-2\n"
    if name == "circuits.geojson":
        return b'{"type":"FeatureCollection","features":[]}'
    if name == "labor_hours.csv":
        return b"damage_type,hours\nwire_down,1\n"
    if name == "priority_nodes.csv":
        return b"node_id\nN-1\n"
    if name == "meta.json":
        return b'{"n_events": 1}'
    if name == "damage_mix.json":
        return b'{"substation":{"wire_down":1}}'
    if name == "multipliers.json":
        return b'{"indirect_labor_multiplier": 1}'
    return b'{"limited": 1}'


class FakeBody:
    def __init__(self, value: bytes):
        self.value = value

    def read(self, _size):
        value, self.value = self.value, b""
        return value


class FakeS3:
    def __init__(self, missing: str | None = None, error: Exception | None = None):
        self.missing = missing
        self.error = error
        self.keys = []

    def get_object(self, *, Bucket, Key):
        self.keys.append((Bucket, Key))
        name = Key.rsplit("/", 1)[-1]
        if name == self.missing or self.error:
            raise self.error or FileNotFoundError(name)
        return {"Body": FakeBody(_artifact_bytes(name))}


def test_s3_downloads_only_allowlisted_artifacts(monkeypatch, tmp_path):
    fake = FakeS3()
    monkeypatch.setattr(data_loader, "DATA_PROCESSED", tmp_path)
    monkeypatch.setattr(data_loader, "S3_ARTIFACTS", ("nodes.csv", "edges.csv", "damage_mix.json"))
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: fake)
    monkeypatch.setenv("STORMHAVEN_S3_BUCKET", "private-bucket")
    monkeypatch.setenv("STORMHAVEN_S3_PREFIX", "real-data")

    data_loader._download_s3_artifacts()

    assert [key for _, key in fake.keys] == ["real-data/nodes.csv", "real-data/edges.csv", "real-data/damage_mix.json"]
    assert (tmp_path / "nodes.csv").read_bytes() == _artifact_bytes("nodes.csv")


def test_s3_missing_object_fails_explicitly(monkeypatch, tmp_path):
    monkeypatch.setattr(data_loader, "DATA_PROCESSED", tmp_path)
    monkeypatch.setattr(data_loader, "S3_ARTIFACTS", ("nodes.csv",))
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: FakeS3(missing="nodes.csv"))
    monkeypatch.setenv("STORMHAVEN_S3_BUCKET", "private-bucket")

    with pytest.raises(RuntimeError, match="nodes.csv"):
        data_loader._download_s3_artifacts()


def test_s3_permissions_failure_is_not_silent(monkeypatch, tmp_path):
    monkeypatch.setattr(data_loader, "DATA_PROCESSED", tmp_path)
    monkeypatch.setattr(data_loader, "S3_ARTIFACTS", ("nodes.csv",))
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: FakeS3(error=PermissionError("denied")))
    monkeypatch.setenv("STORMHAVEN_S3_BUCKET", "private-bucket")

    with pytest.raises(RuntimeError, match="nodes.csv"):
        data_loader._download_s3_artifacts()


def test_s3_disabled_preserves_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(data_loader, "DATA_PROCESSED", tmp_path)
    monkeypatch.delenv("STORMHAVEN_S3_ENABLED", raising=False)
    monkeypatch.delenv("STORMHAVEN_DATA", raising=False)

    store = data_loader.get_store.__wrapped__()

    assert store.is_synthetic is True
