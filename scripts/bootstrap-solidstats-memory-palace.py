#!/usr/bin/env python3
"""Bootstrap and validate the exact MemPalace v3.5.0 Qdrant palace."""

from __future__ import annotations

import json
import hashlib
import math
import os
import posixpath
from pathlib import Path
import shutil
import stat
import sys
import tarfile


COLLECTION = "mempalace_drawers"
DIMENSION = 384
EMBEDDER = "embeddinggemma"
NAMESPACE = "SolidStats"
QDRANT_URL = "http://qdrant:6333"
PROBE_DOCUMENT = "SolidStats runtime bootstrap probe"
PROBE_ID = "solidstats-runtime-bootstrap-probe"
MODEL_REVISION = "5090578d9565bb06545b4552f76e6bc2c93e4a66"
MODEL_ARCHIVE_ROOT = "huggingface"
MODEL_REPOSITORY_ROOT = (
    "huggingface/hub/models--onnx-community--embeddinggemma-300m-ONNX"
)
MODEL_SEED_MARKER = "embeddinggemma-cache.sha256"


class BootstrapError(RuntimeError):
    """A value-free runtime bootstrap failure."""


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise BootstrapError("required runtime binding is unavailable")
    return value


def regular_private(path: Path, *, required_file: bool = True) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        if required_file:
            raise BootstrapError("runtime metadata is unavailable") from None
        return False
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
    ):
        raise BootstrapError("runtime metadata is unsafe")
    return True


def configuration() -> tuple[Path, str, str]:
    palace = Path(required("MEMPALACE_PALACE_PATH"))
    if not palace.is_absolute() or palace == Path("/"):
        raise BootstrapError("palace path is invalid")
    if palace.exists() and (palace.is_symlink() or not palace.is_dir()):
        raise BootstrapError("palace path is unsafe")
    if required("MEMPALACE_EMBEDDING_MODEL") != EMBEDDER:
        raise BootstrapError("embedder model is invalid")
    if required("MEMPALACE_EMBEDDING_DEVICE") != "cpu":
        raise BootstrapError("embedder device is invalid")
    if required("MEMPALACE_QDRANT_URL") != QDRANT_URL:
        raise BootstrapError("Qdrant URL is invalid")
    if required("MEMPALACE_QDRANT_NAMESPACE") != NAMESPACE:
        raise BootstrapError("Qdrant namespace is invalid")
    if required("HF_HUB_OFFLINE") != "1":
        raise BootstrapError("offline model mode is required")
    if required("HF_HUB_DISABLE_TELEMETRY") != "1":
        raise BootstrapError("model telemetry must be disabled")
    if Path(required("HF_HOME")) != palace / ".cache" / "huggingface":
        raise BootstrapError("model cache path is invalid")
    logical_alias = required("SOLIDSTATS_MEMORY_LOGICAL_ALIAS")
    physical_collection = required("SOLIDSTATS_MEMORY_PHYSICAL_COLLECTION")
    if logical_alias == physical_collection:
        raise BootstrapError("logical alias and physical collection collide")
    return palace, logical_alias, physical_collection


def model_vector() -> list[float]:
    try:
        from mempalace.embedding import get_embedding_function

        vectors = get_embedding_function(device="cpu", model=EMBEDDER)(
            input=[PROBE_DOCUMENT]
        )
    except Exception as error:
        raise BootstrapError("embeddinggemma cache is unavailable") from error
    if (
        not isinstance(vectors, list)
        or len(vectors) != 1
        or not isinstance(vectors[0], list)
        or len(vectors[0]) != DIMENSION
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vectors[0]
        )
    ):
        raise BootstrapError("embeddinggemma output contract is invalid")
    return vectors[0]


class DigestReader:
    """Count and hash the exact cache archive stream consumed by tarfile."""

    def __init__(self, source):
        self.source = source
        self.size = 0
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        value = self.source.read(size)
        self.size += len(value)
        self.digest.update(value)
        return value


def cache_binding() -> tuple[Path, str, int]:
    palace = Path(required("MEMPALACE_PALACE_PATH"))
    if not palace.is_absolute() or palace == Path("/"):
        raise BootstrapError("palace path is invalid")
    if required("MEMPALACE_EMBEDDING_MODEL") != EMBEDDER:
        raise BootstrapError("embedder model is invalid")
    if required("SOLIDSTATS_MEMORY_MODEL_REVISION") != MODEL_REVISION:
        raise BootstrapError("model revision is invalid")
    archive_sha256 = required("SOLIDSTATS_MEMORY_MODEL_ARCHIVE_SHA256")
    if len(archive_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in archive_sha256
    ):
        raise BootstrapError("model archive binding is invalid")
    try:
        archive_size = int(required("SOLIDSTATS_MEMORY_MODEL_ARCHIVE_BYTES"))
    except ValueError as error:
        raise BootstrapError("model archive binding is invalid") from error
    if archive_size <= 0:
        raise BootstrapError("model archive binding is invalid")
    return palace, archive_sha256, archive_size


def cache_ready(palace: Path, archive_sha256: str) -> None:
    cache = palace / ".cache" / MODEL_ARCHIVE_ROOT
    marker = cache / MODEL_SEED_MARKER
    regular_private(marker)
    if marker.read_text(encoding="ascii") != archive_sha256 + "\n":
        raise BootstrapError("model cache binding drifted")
    revision = (
        cache
        / "hub"
        / "models--onnx-community--embeddinggemma-300m-ONNX"
        / "snapshots"
        / MODEL_REVISION
    )
    if cache.is_symlink() or not cache.is_dir() or not revision.is_dir():
        raise BootstrapError("model cache is unavailable")


def safe_archive_name(name: str) -> str:
    normalized = posixpath.normpath(name.rstrip("/"))
    if (
        not normalized
        or normalized == "."
        or normalized.startswith("/")
        or normalized == ".."
        or normalized.startswith("../")
        or normalized.split("/", 1)[0] != MODEL_ARCHIVE_ROOT
    ):
        raise BootstrapError("model archive layout is invalid")
    return normalized


def seed_cache(palace: Path, archive_sha256: str, archive_size: int) -> None:
    cache_root = palace / ".cache"
    cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if cache_root.is_symlink() or not cache_root.is_dir():
        raise BootstrapError("model cache path is unsafe")
    destination = cache_root / MODEL_ARCHIVE_ROOT
    staging = cache_root / f"{MODEL_ARCHIVE_ROOT}.seed"
    if staging.exists() or staging.is_symlink():
        raise BootstrapError("model cache staging path is not clean")
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise BootstrapError("model cache destination is unsafe")
        marker = destination / MODEL_SEED_MARKER
        if marker.exists() or marker.is_symlink():
            cache_ready(palace, archive_sha256)
            return
        if any(destination.iterdir()):
            raise BootstrapError("unbound model cache already exists")
        destination.rmdir()
    staging.mkdir(mode=0o700)
    reader = DigestReader(sys.stdin.buffer)
    member_count = 0
    try:
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                member_count += 1
                name = safe_archive_name(member.name)
                relative = name.split("/", 1)[1] if "/" in name else ""
                target = staging / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    os.chmod(target, 0o700)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    source = archive.extractfile(member)
                    if source is None:
                        raise BootstrapError("model archive member is unavailable")
                    descriptor = os.open(
                        target,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                    )
                    with os.fdopen(descriptor, "wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                elif member.issym():
                    if posixpath.isabs(member.linkname):
                        raise BootstrapError("model archive symlink is unsafe")
                    resolved = posixpath.normpath(
                        posixpath.join(posixpath.dirname(name), member.linkname)
                    )
                    if not (
                        resolved == MODEL_REPOSITORY_ROOT
                        or resolved.startswith(MODEL_REPOSITORY_ROOT + "/")
                    ):
                        raise BootstrapError("model archive symlink is unsafe")
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    target.symlink_to(member.linkname)
                else:
                    raise BootstrapError("model archive member type is invalid")
        while reader.read(1024 * 1024):
            pass
        revision = (
            staging
            / "hub"
            / "models--onnx-community--embeddinggemma-300m-ONNX"
            / "snapshots"
            / MODEL_REVISION
        )
        if (
            member_count != 23
            or reader.size != archive_size
            or reader.digest.hexdigest() != archive_sha256
            or not revision.is_dir()
        ):
            raise BootstrapError("model archive verification failed")
        marker = staging / MODEL_SEED_MARKER
        descriptor = os.open(
            marker,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(archive_sha256 + "\n")
        staging.rename(destination)
    except Exception:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def backend_handles(palace: Path):
    try:
        from mempalace.backends.base import EmbedderIdentity, PalaceRef
        from mempalace.backends.qdrant import QdrantBackend, _QdrantConfig
    except (ImportError, AttributeError) as error:
        raise BootstrapError("pinned MemPalace backend contract is unavailable") from error
    reference = PalaceRef(id=str(palace), local_path=str(palace))
    config = _QdrantConfig.from_options(
        {
            "url": QDRANT_URL,
            "api_key": required("MEMPALACE_QDRANT_API_KEY"),
            "namespace": NAMESPACE,
        }
    )
    return QdrantBackend(), reference, config, EmbedderIdentity


def validate_local(palace: Path) -> None:
    marker_path = palace / "qdrant_backend.json"
    sidecar_path = palace / "mempalace_embedder.json"
    regular_private(marker_path)
    regular_private(sidecar_path)
    backend, reference, config, EmbedderIdentity = backend_handles(palace)
    try:
        backend._validate_marker_target(reference, config)
        marker = backend._read_marker(reference)
        expected_target = backend._marker_target(reference, config)
        identity = backend._get_embedder_identity(reference, COLLECTION)
    except Exception as error:
        raise BootstrapError("runtime palace metadata validation failed") from error
    if (
        not isinstance(marker, dict)
        or set(marker)
        != {"backend", "schema_version", "created_at", "palace_id", "qdrant"}
        or marker.get("backend") != "qdrant"
        or marker.get("schema_version") != 1
        or marker.get("palace_id") != str(palace)
        or marker.get("qdrant") != expected_target
        or not isinstance(marker.get("created_at"), str)
        or not marker["created_at"]
        or identity != EmbedderIdentity(model_name=EMBEDDER, dimension=DIMENSION)
    ):
        raise BootstrapError("runtime palace metadata drifted")


def cleanup_probe(collection, before_count: int) -> bool:
    try:
        collection.delete(ids=[PROBE_ID])
        remaining = collection.get(ids=[PROBE_ID], include=["metadatas"])
        return collection.count() == before_count and not remaining.ids
    except Exception:
        return False


def online_bootstrap(palace: Path, expected_count: int) -> None:
    marker_path = palace / "qdrant_backend.json"
    sidecar_path = palace / "mempalace_embedder.json"
    marker_existed = regular_private(marker_path, required_file=False)
    sidecar_existed = regular_private(sidecar_path, required_file=False)
    if marker_existed != sidecar_existed:
        raise BootstrapError("runtime palace metadata is incomplete")

    backend, reference, config, EmbedderIdentity = backend_handles(palace)
    try:
        collection = backend.get_collection(
            palace=reference,
            collection_name=COLLECTION,
            create=not marker_existed,
            options={
                "url": config.url,
                "api_key": config.api_key,
                "namespace": config.namespace,
            },
        )
        before_count = collection.count()
    except Exception as error:
        raise BootstrapError("logical alias is unavailable") from error
    if before_count != expected_count:
        raise BootstrapError("logical alias count is invalid")

    if marker_existed:
        validate_local(palace)
        return

    try:
        existing = collection.get(ids=[PROBE_ID], include=["metadatas"])
    except Exception as error:
        raise BootstrapError("bootstrap probe pre-state is unavailable") from error
    if existing.ids:
        raise BootstrapError("bootstrap probe identifier already exists")

    wrote_probe = False
    restored = False
    try:
        collection.upsert(
            documents=[PROBE_DOCUMENT],
            ids=[PROBE_ID],
            metadatas=[{"_solidstats_runtime_bootstrap": True}],
            embeddings=[model_vector()],
        )
        wrote_probe = True
        inserted = collection.get(ids=[PROBE_ID], include=["metadatas"])
        if collection.count() != before_count + 1 or inserted.ids != [PROBE_ID]:
            raise BootstrapError("bootstrap probe write was not isolated")
        restored = cleanup_probe(collection, before_count)
        if not restored:
            raise BootstrapError("bootstrap probe cleanup failed")
        collection.set_embedder_identity(
            EmbedderIdentity(model_name=EMBEDDER, dimension=DIMENSION)
        )
        validate_local(palace)
    except Exception:
        if wrote_probe and not restored:
            restored = cleanup_probe(collection, before_count)
        if restored:
            for path, existed in (
                (sidecar_path, sidecar_existed),
                (marker_path, marker_existed),
            ):
                if not existed:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
        raise


def positive_count() -> int:
    raw = required("SOLIDSTATS_MEMORY_EXPECTED_COUNT")
    try:
        value = int(raw)
    except ValueError as error:
        raise BootstrapError("expected count is invalid") from error
    if value <= 0 or str(value) != raw:
        raise BootstrapError("expected count is invalid")
    return value


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in {
        "cache-ready",
        "seed-cache",
        "offline",
        "online",
    }:
        return 64
    try:
        if argv[0] in {"cache-ready", "seed-cache"}:
            palace, archive_sha256, archive_size = cache_binding()
            if argv[0] == "seed-cache":
                seed_cache(palace, archive_sha256, archive_size)
            cache_ready(palace, archive_sha256)
            print("embeddinggemma cache ready")
            return 0
        palace, logical_alias, _physical_collection = configuration()
        expected_alias = (
            "mempalace_"
            + NAMESPACE
            + "_"
            + hashlib.sha256(
                str(palace).encode("utf-8", errors="surrogatepass")
            ).hexdigest()[:16]
            + "_"
            + COLLECTION
        )
        if logical_alias != expected_alias:
            raise BootstrapError("logical alias binding is invalid")
        model_vector()
        if argv[0] == "online":
            online_bootstrap(palace, positive_count())
        else:
            validate_local(palace)
        print("mempalace runtime palace ready")
        return 0
    except (BootstrapError, OSError, ValueError, json.JSONDecodeError):
        print("bootstrap refused: runtime palace contract failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
