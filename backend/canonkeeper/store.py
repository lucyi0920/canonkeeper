"""Persistence: documents (Firestore) and binary assets (Cloud Storage).

The app is stateless; any Cloud Run instance can serve any request. Local
development and tests use the in-memory backends.
"""
from __future__ import annotations

import base64
import mimetypes
import threading
import uuid
from typing import Optional

from . import config


class DocStore:
    def get(self, col: str, doc_id: str) -> Optional[dict]: ...
    def set(self, col: str, doc_id: str, data: dict) -> None: ...
    def update(self, col: str, doc_id: str, data: dict) -> None: ...
    def append(self, col: str, doc_id: str, field: str, item: dict) -> None: ...


class MemoryDocStore(DocStore):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def get(self, col, doc_id):
        with self._lock:
            doc = self._data.get(col, {}).get(doc_id)
            return None if doc is None else _deepcopy(doc)

    def set(self, col, doc_id, data):
        with self._lock:
            self._data.setdefault(col, {})[doc_id] = _deepcopy(data)

    def update(self, col, doc_id, data):
        with self._lock:
            self._data.setdefault(col, {}).setdefault(doc_id, {}).update(_deepcopy(data))

    def append(self, col, doc_id, field, item):
        with self._lock:
            self._data.setdefault(col, {}).setdefault(doc_id, {}).setdefault(field, []).append(_deepcopy(item))


class FirestoreDocStore(DocStore):
    def __init__(self) -> None:
        from google.cloud import firestore
        self._fs = firestore
        self._db = firestore.Client(project=config.GCP_PROJECT)

    def get(self, col, doc_id):
        snap = self._db.collection(col).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def set(self, col, doc_id, data):
        self._db.collection(col).document(doc_id).set(data)

    def update(self, col, doc_id, data):
        self._db.collection(col).document(doc_id).set(data, merge=True)

    def append(self, col, doc_id, field, item):
        self._db.collection(col).document(doc_id).set({field: self._fs.ArrayUnion([item])}, merge=True)


class AssetStore:
    """Asset refs: 'seed:<file>' (bundled demo art) or 'asset:<id>' (uploaded / generated)."""

    def put(self, data: bytes, mime: str) -> str:
        asset_id = uuid.uuid4().hex
        self._put(asset_id, data, mime)
        return f"asset:{asset_id}"

    def get(self, ref: str) -> tuple[bytes, str]:
        kind, _, key = ref.partition(":")
        if kind == "seed":
            path = (config.SEED_DIR / "panels" / key).resolve()
            if path.parent != (config.SEED_DIR / "panels").resolve() or not path.exists():
                raise KeyError(ref)
            return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/jpeg"
        if kind == "asset":
            return self._get(key)
        raise KeyError(ref)

    def _put(self, asset_id: str, data: bytes, mime: str) -> None: ...
    def _get(self, asset_id: str) -> tuple[bytes, str]: ...


class MemoryAssetStore(AssetStore):
    def __init__(self) -> None:
        self._blobs: dict[str, tuple[bytes, str]] = {}

    def _put(self, asset_id, data, mime):
        self._blobs[asset_id] = (data, mime)

    def _get(self, asset_id):
        if asset_id not in self._blobs:
            raise KeyError(asset_id)
        return self._blobs[asset_id]


class GcsAssetStore(AssetStore):
    def __init__(self) -> None:
        from google.cloud import storage
        self._bucket = storage.Client(project=config.GCP_PROJECT).bucket(config.ASSET_BUCKET)
        self._cache: dict[str, tuple[bytes, str]] = {}

    def _put(self, asset_id, data, mime):
        blob = self._bucket.blob(f"assets/{asset_id}")
        blob.upload_from_string(data, content_type=mime)
        self._cache[asset_id] = (data, mime)

    def _get(self, asset_id):
        if asset_id in self._cache:
            return self._cache[asset_id]
        blob = self._bucket.blob(f"assets/{asset_id}")
        if not blob.exists():
            raise KeyError(asset_id)
        data = blob.download_as_bytes()
        out = (data, blob.content_type or "application/octet-stream")
        if len(self._cache) < 256:
            self._cache[asset_id] = out
        return out


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:") or "," not in data_url:
        raise ValueError("expected a data: URL")
    header, b64 = data_url.split(",", 1)
    mime = header[5:].split(";")[0] or "application/octet-stream"
    return base64.b64decode(b64), mime


def _deepcopy(obj):
    import copy
    return copy.deepcopy(obj)


_docs: Optional[DocStore] = None
_assets: Optional[AssetStore] = None


def docs() -> DocStore:
    global _docs
    if _docs is None:
        _docs = FirestoreDocStore() if config.STORE_BACKEND == "gcp" else MemoryDocStore()
    return _docs


def assets() -> AssetStore:
    global _assets
    if _assets is None:
        _assets = GcsAssetStore() if config.STORE_BACKEND == "gcp" else MemoryAssetStore()
    return _assets
