#!/usr/bin/env python3
"""Complete, versioned unified-palace recovery packages; no implicit cutover."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import ssl
import tarfile
import tempfile
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree
from urllib import request, parse, error

SCHEMA = "unified-memory-recovery/v1"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SHA = re.compile(r"^[0-9a-f]{64}$")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def private_json(path, value):
    path = Path(path)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def bindings(value):
    rows = value.get("collections", [])
    if not rows or not isinstance(rows, list):
        raise ValueError("complete collection bindings required")
    names = set()
    logical = set()
    for row in rows:
        if set(row) != {"logicalName", "alias", "physical", "dimension", "distance"}:
            raise ValueError("collection binding fields differ")
        if row["logicalName"] not in {"mempalace_drawers", "mempalace_closets"}:
            raise ValueError("unclassified collection")
        if row["logicalName"] in logical:
            raise ValueError("duplicate logical collection")
        logical.add(row["logicalName"])
        for field in ("alias", "physical"):
            name = row[field]
            if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
                raise ValueError("unsafe or duplicate collection identity")
            names.add(name)
        if type(row["dimension"]) is not int or row["dimension"] <= 0 or row["distance"] != "Cosine":
            raise ValueError("invalid vector configuration")
    if logical != {"mempalace_drawers", "mempalace_closets"}:
        raise ValueError("complete drawers and closets inventory required")
    return rows


def tree_digest(root):
    root = Path(root)
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute():
                raise ValueError("absolute local state symlink")
            resolved = path.resolve(strict=True)
            resolved.relative_to(root.resolve())
            if not resolved.is_file():
                raise ValueError("unsupported local state symlink target")
            result.update(path.relative_to(root).as_posix().encode() + b"\0L\0" + target.encode() + b"\0")
            result.update(bytes.fromhex(digest(resolved)))
        elif path.is_file():
            result.update(path.relative_to(root).as_posix().encode() + b"\0F\0")
            result.update(bytes.fromhex(digest(path)))
        elif not path.is_dir():
            raise ValueError("local state contains unsupported file type")
    return result.hexdigest()


def sqlite_checks(root):
    results = {}
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            header = stream.read(16)
        if header != b"SQLite format 3\0":
            continue
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("SQLite integrity failed")
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            counts = {}
            for (name,) in tables:
                quoted = '"' + name.replace('"', '""') + '"'
                counts[name] = connection.execute("SELECT count(*) FROM " + quoted).fetchone()[0]
            results[path.relative_to(root).as_posix()] = counts
        finally:
            connection.close()
    return results


class Qdrant:
    def __init__(self, url, key):
        self.url = url.rstrip("/")
        self.key = key

    def call(self, method, path, body=None, output=None):
        headers = {"api-key": self.key, "Content-Type": "application/json"}
        data = None if body is None else canonical(body)
        operation = request.Request(self.url + path, data=data, headers=headers, method=method)
        with request.urlopen(operation, timeout=900) as response:
            if output is not None:
                with Path(output).open("xb") as stream:
                    shutil.copyfileobj(response, stream, length=1024 * 1024)
                return None
            return json.load(response)["result"]

    def fingerprint(self, collection):
        offset = None
        count = 0
        hasher = hashlib.sha256()
        # Qdrant scroll is ID ordered. Preserve payload and stored vectors exactly.
        while True:
            query = {"limit": 128, "with_payload": True, "with_vector": True}
            if offset is not None:
                query["offset"] = offset
            page = self.call("POST", "/collections/" + collection + "/points/scroll", query)
            for point in page["points"]:
                hasher.update(canonical(point) + b"\n")
                count += 1
            offset = page.get("next_page_offset")
            if offset is None:
                return {"count": count, "sha256": hasher.hexdigest()}

    def recover(self, target, snapshot):
        # Multipart upload is operator-only. Stream the file instead of loading it.
        boundary = "unified-memory-" + digest(snapshot)[:24]
        start = ("--" + boundary + '\r\nContent-Disposition: form-data; name="snapshot"; filename="collection.snapshot"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
        end = ("\r\n--" + boundary + "--\r\n").encode()
        url = parse.urlsplit(self.url)
        connection_type = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(url.hostname, url.port, timeout=900)
        path = url.path.rstrip("/") + "/collections/" + target + "/snapshots/upload?priority=snapshot&wait=true"
        try:
            connection.putrequest("POST", path)
            connection.putheader("api-key", self.key)
            connection.putheader("Content-Type", "multipart/form-data; boundary=" + boundary)
            connection.putheader("Content-Length", str(len(start) + Path(snapshot).stat().st_size + len(end)))
            connection.endheaders()
            connection.send(start)
            with Path(snapshot).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    connection.send(chunk)
            connection.send(end)
            response = connection.getresponse()
            if response.status != 200 or json.load(response).get("status") != "ok":
                raise ValueError("isolated snapshot recovery failed")
        finally:
            connection.close()


def backup(client, config, palace, output):
    rows = bindings(config)
    palace, output = Path(palace), Path(output)
    if output.exists():
        raise ValueError("backup output must be absent")
    output.mkdir(mode=0o700)
    sqlite = sqlite_checks(palace)
    before = tree_digest(palace)
    manifest = {"schema": SCHEMA, "qdrantVersion": config["qdrantVersion"], "collections": [], "sqlite": sqlite}
    for index, row in enumerate(rows):
        name = row["physical"]
        info = client.call("GET", "/collections/" + name)
        vectors = info["config"]["params"]["vectors"]
        if vectors.get("size") != row["dimension"] or vectors.get("distance") != row["distance"]:
            raise ValueError("source vector configuration differs")
        fingerprint = client.fingerprint(name)
        snapshot = client.call("POST", "/collections/" + name + "/snapshots")
        filename = "collection-" + str(index) + ".snapshot"
        # Delete only this run's exact transient snapshot, even on download/parity failure.
        snapshot_path = "/collections/" + name + "/snapshots/" + parse.quote(snapshot["name"], safe="")
        try:
            client.call("GET", snapshot_path, output=output / filename)
            if client.fingerprint(name) != fingerprint:
                raise ValueError("collection changed while frozen")
        finally:
            client.call("DELETE", snapshot_path)
        manifest["collections"].append({**row, "file": filename, "fingerprint": fingerprint, "config": vectors})
    archive_path = output / "local-state.tar"
    with tarfile.open(archive_path, "w") as archive:
        archive.add(palace, arcname="palace", recursive=True)
    after = tree_digest(palace)
    if before != after:
        raise ValueError("local state changed while frozen")
    manifest["localState"] = {"sha256": before, "file": "local-state.tar"}
    manifest["members"] = {path.name: digest(path) for path in sorted(output.iterdir())}
    private_json(output / "manifest.json", manifest)
    validate_package(output)
    private_json(output / "COMPLETE.json", {"schema": SCHEMA, "manifestSha256": digest(output / "manifest.json")})
    return manifest


def archive_preflight(archive_path, target_parent):
    # This schema writes uncompressed tar. Reject compression before metadata scans.
    members, names, expanded = [], set(), 0
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive:
            if len(members) >= 100000 or len(member.name) > 4096 or member.name in names:
                raise ValueError("archive metadata limits exceeded")
            names.add(member.name)
            parts = Path(member.name).parts
            if not parts or parts[0] != "palace" or ".." in parts or Path(member.name).is_absolute():
                raise ValueError("unsafe archive path")
            if getattr(member, "sparse", None):
                raise ValueError("sparse archive members rejected")
            if member.issym():
                link = (Path(target_parent) / member.name).parent / member.linkname
                if Path(member.linkname).is_absolute():
                    raise ValueError("absolute archive symlink")
                link.resolve().relative_to(Path(target_parent).resolve())
            elif not (member.isdir() or member.isfile()):
                raise ValueError("unsupported archive member")
            if member.isfile():
                expanded += member.size
                if expanded > 16 * 1024 ** 3:
                    raise ValueError("archive expanded size limit exceeded")
            members.append(member)
    if shutil.disk_usage(target_parent).free < expanded:
        raise ValueError("insufficient isolated state space")
    return members


def extract_state(archive_path, target):
    target = Path(target)
    members = archive_preflight(archive_path, target.parent)
    target.mkdir(mode=0o700)
    with tarfile.open(archive_path, mode="r:") as archive:
        archive.extractall(target, members=members, filter="data")
    return target / "palace"

def validate_package(package, require_complete=False):
    package = Path(package)
    if package.is_symlink() or any(path.is_symlink() for path in package.iterdir()):
        raise ValueError("unsafe package path")
    manifest = json.loads((package / "manifest.json").read_text())
    if manifest.get("schema") != SCHEMA or not isinstance(manifest.get("members"), dict):
        raise ValueError("invalid recovery package")
    bindings({"collections": [{k: row[k] for k in ("logicalName", "alias", "physical", "dimension", "distance")} for row in manifest["collections"]]})
    expected = {"local-state.tar"} | {"collection-" + str(i) + ".snapshot" for i in range(len(manifest["collections"]))}
    if set(manifest["members"]) != expected:
        raise ValueError("incomplete package member inventory")
    actual = {path.name for path in package.iterdir()}
    if actual not in (expected | {"manifest.json"}, expected | {"manifest.json", "COMPLETE.json"}):
        raise ValueError("package inventory differs")
    for name, checksum in manifest["members"].items():
        path = package / name
        if not SHA.fullmatch(checksum) or path.is_symlink() or not path.is_file() or digest(path) != checksum:
            raise ValueError("package checksum differs")
    for index, row in enumerate(manifest["collections"]):
        if row["file"] != "collection-" + str(index) + ".snapshot":
            raise ValueError("snapshot inventory differs")
    if require_complete:
        complete = json.loads((package / "COMPLETE.json").read_text())
        if complete != {"schema": SCHEMA, "manifestSha256": digest(package / "manifest.json")}:
            raise ValueError("recovery point is incomplete")
    with tempfile.TemporaryDirectory(prefix="unified-recovery-check-") as temporary:
        state = extract_state(package / "local-state.tar", Path(temporary) / "state")
        if tree_digest(state) != manifest["localState"]["sha256"] or sqlite_checks(state) != manifest["sqlite"]:
            raise ValueError("local state parity differs")
    return manifest


def restore(client, package, targets, protected, state_output):
    manifest = validate_package(package, require_complete=True)
    source_names = {row["physical"] for row in manifest["collections"]}
    if not isinstance(protected, list) and not isinstance(protected, set):
        raise ValueError("protected identity inventory required")
    protected = set(protected)
    if not protected or any(not isinstance(name, str) or not NAME.fullmatch(name) for name in protected):
        raise ValueError("protected identity inventory required")
    if set(targets) != source_names or len(set(targets.values())) != len(targets):
        raise ValueError("complete unique restore targets required")
    if Path(state_output).exists():
        raise ValueError("isolated state target exists")
    with tarfile.open(Path(package) / "local-state.tar") as archive:
        needed = sum(member.size for member in archive if member.isfile())
    if shutil.disk_usage(Path(state_output).parent).free < needed:
        raise ValueError("insufficient isolated state space")
    restored_targets = set()
    def check_targets():
        collections = {row["name"] for row in client.call("GET", "/collections")["collections"]}
        aliases = client.call("GET", "/aliases")["aliases"]
        occupied = collections | {row["alias_name"] for row in aliases} | {row["collection_name"] for row in aliases}
        for name in set(targets.values()) - restored_targets:
            if not isinstance(name, str) or not NAME.fullmatch(name) or name in occupied | protected | source_names:
                raise ValueError("restore target is protected or occupied")
        return aliases
    aliases_before = check_targets()
    for row in manifest["collections"]:
        target = targets[row["physical"]]
        check_targets()
        client.recover(target, Path(package) / row["file"])
        restored_targets.add(target)
        info = client.call("GET", "/collections/" + target)
        if info["config"]["params"]["vectors"] != row["config"] or client.fingerprint(target) != row["fingerprint"]:
            raise ValueError("restored collection parity differs")
    state = extract_state(Path(package) / "local-state.tar", state_output)
    if tree_digest(state) != manifest["localState"]["sha256"] or sqlite_checks(state) != manifest["sqlite"]:
        raise ValueError("restored state parity differs")
    if client.call("GET", "/aliases")["aliases"] != aliases_before:
        raise ValueError("aliases changed during isolated restore")
    # Deliberately no alias publication: this command is a recovery drill.
    return {"schema": SCHEMA, "restored": len(targets), "aliasesChanged": False}


class S3:
    """Path-style SigV4 object transfer with bounded memory; no bucket-policy mutation."""
    def __init__(self, endpoint, bucket, prefix, region="ru-1"):
        self.url = parse.urlsplit(endpoint)
        if self.url.scheme != "https" or self.url.username or self.url.path not in ("", "/"):
            raise ValueError("HTTPS object endpoint required")
        if not bucket or not prefix.startswith("backups/unified-memory/") or ".." in prefix:
            raise ValueError("invalid unified recovery prefix")
        self.bucket, self.prefix, self.region = bucket, prefix.rstrip("/") + "/", region

    def transfer(self, method, name, path, *, query=None, bucket_root=False):
        now = datetime.now(timezone.utc)
        stamp, date = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        key_id = os.environ["AWS_ACCESS_KEY_ID"]
        secret = os.environ["AWS_SECRET_ACCESS_KEY"]
        payload_hash = digest(path) if method == "PUT" else hashlib.sha256(b"").hexdigest()
        uri = "/" + parse.quote(self.bucket if bucket_root else self.bucket + "/" + self.prefix + name, safe="/-_.~")
        query_text = "&".join(parse.quote(key, safe="-_.~") + "=" + parse.quote(str(value), safe="-_.~") for key, value in sorted((query or {}).items()))
        headers = {"host": self.url.netloc, "x-amz-content-sha256": payload_hash, "x-amz-date": stamp}
        session = os.environ.get("AWS_SESSION_TOKEN")
        if session:
            headers["x-amz-security-token"] = session
        signed = ";".join(sorted(headers))
        header_text = "".join(key + ":" + headers[key] + "\n" for key in sorted(headers))
        canonical_request = method + "\n" + uri + "\n" + query_text + "\n" + header_text + "\n" + signed + "\n" + payload_hash
        scope = date + "/" + self.region + "/s3/aws4_request"
        message = "AWS4-HMAC-SHA256\n" + stamp + "\n" + scope + "\n" + hashlib.sha256(canonical_request.encode()).hexdigest()
        signing = ("AWS4" + secret).encode()
        for part in (date, self.region, "s3", "aws4_request"):
            signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(signing, message.encode(), hashlib.sha256).hexdigest()
        headers["Authorization"] = "AWS4-HMAC-SHA256 Credential=" + key_id + "/" + scope + ", SignedHeaders=" + signed + ", Signature=" + signature
        connection = http.client.HTTPSConnection(self.url.hostname, self.url.port, timeout=900)
        try:
            connection.putrequest(method, uri + ("?" + query_text if query_text else ""), skip_host=True)
            for key, value in headers.items():
                connection.putheader(key, value)
            connection.putheader("Content-Length", str(Path(path).stat().st_size) if method == "PUT" else "0")
            connection.endheaders()
            if method == "PUT":
                with Path(path).open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        connection.send(chunk)
            response = connection.getresponse()
            if response.status not in (200, 201, 204):
                raise ValueError("object transfer failed")
            if method == "GET":
                with Path(path).open("xb") as stream:
                    if bucket_root or name.endswith(("manifest.json", "COMPLETE.json")):
                        content = response.read(2 * 1024 * 1024 + 1)
                        if len(content) > 2 * 1024 * 1024:
                            raise ValueError("object-store metadata limit exceeded")
                        stream.write(content)
                    else:
                        shutil.copyfileobj(response, stream, length=1024 * 1024)
            else:
                response.read()
        finally:
            connection.close()

    def metadata(self, query):
        with tempfile.TemporaryDirectory(prefix="unified-s3-metadata-") as temporary:
            path = Path(temporary) / "metadata.xml"
            self.transfer("GET", "", path, query=query, bucket_root=True)
            content = path.read_bytes()
            if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
                raise ValueError("unsafe object-store metadata")
            root = ElementTree.fromstring(content)
            for node in root.iter():
                node.tag = node.tag.rsplit("}", 1)[-1]
            return root

    def require_unversioned(self):
        root = self.metadata({"versioning": ""})
        if root.tag != "VersioningConfiguration" or root.findtext("Status") not in (None, "Disabled"):
            raise ValueError("unversioned bucket evidence required; ordinary delete cannot purge old versions")

    def objects(self):
        if self.prefix != "backups/unified-memory/":
            raise ValueError("retention requires exact unified root prefix")
        objects, token, seen = [], None, set()
        for page in range(500):
            query = {"list-type": "2", "prefix": self.prefix, "max-keys": "1000"}
            if token:
                query["continuation-token"] = token
            root = self.metadata(query)
            if root.tag != "ListBucketResult":
                raise ValueError("object inventory unavailable")
            for row in root.findall("Contents"):
                key, modified = row.findtext("Key"), row.findtext("LastModified")
                if not key or not key.startswith(self.prefix) or key in seen or not modified:
                    raise ValueError("object inventory boundary differs")
                seen.add(key)
                size = int(row.findtext("Size", "-1"))
                if size < 0:
                    raise ValueError("object size unavailable")
                objects.append({"key": key, "size": size, "modified": datetime.fromisoformat(modified.replace("Z", "+00:00"))})
                if len(objects) > 100000:
                    raise ValueError("object inventory limit exceeded")
            if root.findtext("IsTruncated") == "false":
                return objects
            next_token = root.findtext("NextContinuationToken")
            if not next_token or next_token == token:
                raise ValueError("object pagination incomplete")
            token = next_token
        raise ValueError("object pagination limit exceeded")

    def prune(self, now=None):
        self.require_unversioned()
        inventory = self.objects()
        groups = {}
        for row in inventory:
            relative = row["key"][len(self.prefix):]
            parts = relative.split("/")
            if len(parts) != 2 or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", parts[0]):
                raise ValueError("unexpected unified recovery object")
            groups.setdefault(parts[0], {})[parts[1]] = row
        complete = sorted(((members["COMPLETE.json"]["modified"], point, members)
                           for point, members in groups.items() if "COMPLETE.json" in members), reverse=True)
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=30)
        for modified, point, members in complete[30:]:
            if modified >= cutoff:
                continue
            with tempfile.TemporaryDirectory(prefix="unified-expired-point-") as temporary:
                package = Path(temporary)
                if shutil.disk_usage(package).free < sum(row["size"] for row in members.values()):
                    raise ValueError("insufficient expired-point verification capacity")
                for name in ("manifest.json", "COMPLETE.json"):
                    self.transfer("GET", point + "/" + name, package / name)
                manifest = json.loads((package / "manifest.json").read_text())
                expected = set(manifest["members"]) | {"manifest.json", "COMPLETE.json"}
                if expected != set(members) or not expected <= {"manifest.json", "COMPLETE.json", "local-state.tar", "collection-0.snapshot", "collection-1.snapshot"}:
                    raise ValueError("expired point inventory differs")
                for name in sorted(manifest["members"]):
                    self.transfer("GET", point + "/" + name, package / name)
                validate_package(package, require_complete=True)
                # Marker first: interrupted cleanup must never advertise a usable partial point.
                for name in ["COMPLETE.json", *sorted(expected - {"COMPLETE.json"})]:
                    self.transfer("DELETE", point + "/" + name, None)
            if any(row["key"].startswith(self.prefix + point + "/") for row in self.objects()):
                raise ValueError("expired recovery point deletion was not confirmed")

    def publish(self, package):
        package = Path(package)
        validate_package(package, require_complete=True)
        names = sorted(path.name for path in package.iterdir() if path.name != "COMPLETE.json")
        with tempfile.TemporaryDirectory(prefix="unified-object-check-") as temporary:
            for name in names:
                self.transfer("PUT", name, package / name)
                downloaded = Path(temporary) / name
                self.transfer("GET", name, downloaded)
                if digest(downloaded) != digest(package / name):
                    raise ValueError("uploaded recovery member differs")
        self.transfer("PUT", "COMPLETE.json", package / "COMPLETE.json")
        with tempfile.TemporaryDirectory(prefix="unified-completion-check-") as temporary:
            downloaded = Path(temporary) / "COMPLETE.json"
            self.transfer("GET", "COMPLETE.json", downloaded)
            if digest(downloaded) != digest(package / "COMPLETE.json"):
                raise ValueError("uploaded completion marker differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "verify", "restore"))
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--palace", type=Path)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--targets", type=Path)
    parser.add_argument("--protected", type=Path)
    parser.add_argument("--state-output", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL"))
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.operation == "verify":
        validate_package(args.package, require_complete=True)
    else:
        key = args.key_file.read_text().strip() if args.key_file else os.environ["QDRANT_API_KEY"]
        client = Qdrant(args.qdrant_url, key)
        if args.operation == "backup":
            if os.environ.get("UNIFIED_WRITERS_QUIESCED") != "1":
                raise ValueError("backup requires coordinator writer quiescence")
            config = json.loads(args.bindings.read_text())
            minimum = config["minimumBackupFreeBytes"]
            if type(minimum) is not int or minimum <= 0 or shutil.disk_usage(args.package.parent).free < minimum:
                raise ValueError("insufficient reviewed backup scratch capacity")
            backup(client, config, args.palace, args.package)
            if args.publish:
                root_store = S3(os.environ["S3_ENDPOINT"], os.environ["S3_BUCKET"], "backups/unified-memory/")
                root_store.require_unversioned()
                S3(os.environ["S3_ENDPOINT"], os.environ["S3_BUCKET"], os.environ["S3_PREFIX"] + os.environ["RECOVERY_POINT"] + "/").publish(args.package)
                root_store.prune()
        else:
            restore(client, args.package, json.loads(args.targets.read_text()), json.loads(args.protected.read_text()), args.state_output)
    print("PASS: unified recovery operation")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Network exception URLs and payloads may carry private state.
        print("FAIL: unified recovery operation", file=__import__("sys").stderr)
        raise SystemExit(1)
