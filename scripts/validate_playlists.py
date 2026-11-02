#!/usr/bin/env python3
"""Validate publication bytes, exact firmware bindings and append-only history offline."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator
from referencing import Registry

SOURCE = "https://raw.githubusercontent.com/Iliya-hj01/pendant-firmware-releases/main/"
INDEX = "playlists/index-v1.json"
LIMITS = {"index": 512 * 1024, "playlist": 64 * 1024, "migration": 1024 * 1024}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class PublicationError(ValueError):
    pass


def fail(path, message):
    raise PublicationError(f"{path}: {message}")


def no_remote_schema(uri):
    fail(uri, "external schema retrieval is forbidden")


def parse_json(raw, path, limit=1024 * 1024):
    if len(raw) > limit:
        fail(path, f"document exceeds {limit} bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(path, "UTF-8 BOM is forbidden")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail(path, f"duplicate object key {key!r}")
            result[key] = value
        return result

    def reject_number(token):
        fail(path, f"only integer number tokens are supported, not {token!r}")

    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs,
            parse_float=reject_number, parse_constant=reject_number,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        fail(path, f"invalid UTF-8/JSON: {error}")

    def visit(value, location, depth):
        if isinstance(value, (dict, list)) and depth >= 32:
            fail(location, "JSON nesting exceeds 32 levels")
        if type(value) is int and not -(2**63) <= value < 2**63:
            fail(location, "integer is outside signed 64-bit bounds")
        if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            fail(location, "unpaired Unicode surrogate")
        if isinstance(value, dict):
            for key, item in value.items():
                visit(key, location, depth)
                visit(item, f"{location}.{key}", depth + 1)
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{location}[{index}]", depth + 1)

    visit(document, path + ":$", 0)
    return document


def local_path(root, relative):
    if (
        not relative or relative.startswith("/") or
        any(char in relative for char in "\\%:?#") or
        any(part in ("", ".", "..") for part in relative.split("/")) or
        str(PurePosixPath(relative)) != relative
    ):
        fail(relative, "noncanonical repository-relative path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        fail(relative, "path escapes the repository")
    return path


def read_bytes(root, relative, limit=1024 * 1024):
    path = local_path(root, relative)
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as error:
        fail(relative, f"cannot read document: {error}")
    if len(raw) > limit:
        fail(relative, f"document exceeds {limit} bytes")
    return raw


def check_schema(document, schema, path):
    validator = Draft202012Validator(schema, registry=Registry(retrieve=no_remote_schema))
    error = next(validator.iter_errors(document), None)
    if error is not None:
        fail(path + ":" + error.json_path, error.message)


def check_text(value, path, maximum, multiline=False, nonempty=True):
    if len(value) > maximum or (nonempty and not value.strip()):
        fail(path, f"text must contain {'1' if nonempty else '0'}..{maximum} code points")
    if any((ord(char) < 32 or 127 <= ord(char) <= 159) and
           not (multiline and char in "\r\n") for char in value):
        fail(path, "unsupported control character")
    if not multiline and (value != value.strip() or unicodedata.normalize("NFC", value) != value):
        fail(path, "text must already be NFC-normalized and trimmed")


def check_slug(value, path):
    if len(value) > 64 or SLUG.fullmatch(value) is None:
        fail(path, "expected a lowercase publication slug of 1..64 characters")


def version(value, path):
    if re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value) is None:
        fail(path, "expected an exact firmware version without leading zeroes")
    parts = tuple(map(int, value.split(".")))
    if parts[0] > 255 or parts[1] > 255 or parts[2] > 65535:
        fail(path, "firmware version exceeds u8.u8.u16")
    return parts


def binding_key(binding):
    return {**binding, "hardwareRevisions": sorted(binding["hardwareRevisions"])}


def check_binding(binding, path):
    if not 1 <= binding["productCode"] <= 65535 or not binding["productKey"].strip():
        fail(path, "invalid product identity")
    hardware = binding["hardwareRevisions"]
    if len(hardware) > 256 or any(not 1 <= item <= 65535 for item in hardware):
        fail(path + ".hardwareRevisions", "hardware revisions exceed supported bounds")
    if not 1 <= binding["definitionRevision"] <= 2**32 - 1:
        fail(path + ".definitionRevision", "definition revision must be a nonzero u32")
    version(binding["firmwareVersion"], path + ".firmwareVersion")


def allowed_values(parameter, path):
    minimum, maximum = parameter["minimum"], parameter["maximum"]
    if not 0 <= minimum <= maximum <= 255:
        fail(path, "invalid byte domain")
    values = ({option["value"] for option in parameter["options"]}
              if parameter["control"] == "list" else set(range(minimum, maximum + 1)))
    if not values or any(type(value) is not int or not minimum <= value <= maximum for value in values):
        fail(path, "invalid option values")
    if parameter["default"] not in values:
        fail(path, "default is outside the parameter domain")
    return values if parameter.get("used", True) else {parameter["default"]}


class FirmwareDefinitions:
    def __init__(self, root):
        self.root = root
        self.catalogue = parse_json(read_bytes(root, "lilum-firmware-catalogue.json"),
                                    "lilum-firmware-catalogue.json")
        shared = parse_json(read_bytes(root, "lilum-firmware-definition.json"),
                            "lilum-firmware-definition.json")
        self.schemas = {entry["schemaVersion"]: entry["schema"] for entry in shared["schemas"]}
        self.resolved = {}

    def resolve(self, binding, path):
        key = json.dumps(binding_key(binding), sort_keys=True)
        if key in self.resolved:
            return self.resolved[key]
        matches = [
            release
            for element in self.catalogue["elements"]
            if (element["productCode"], element["productKey"]) ==
               (binding["productCode"], binding["productKey"])
            for release in element["releases"]
            if release["status"] == "available" and
               release["firmwareVersion"] == binding["firmwareVersion"] and
               release["definitionRevision"] == binding["definitionRevision"] and
               release["document"]["sha256"] == binding["definitionDocumentSha256"] and
               set(binding["hardwareRevisions"]) <= set(release["hardwareRevisions"])
        ]
        if len(matches) != 1:
            fail(path, "binding does not select exactly one available catalogue firmware")
        release = matches[0]
        reference = release["document"]
        if reference["url"] != SOURCE + reference["path"]:
            fail(path, "firmware reference is outside the approved repository source")
        raw = read_bytes(self.root, reference["path"])
        if len(raw) != reference["sizeBytes"] or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            fail(reference["path"], "firmware size or SHA-256 disagrees with catalogue")
        document = parse_json(raw, reference["path"])
        schema = self.schemas.get(document["schemaVersion"])
        if schema is None:
            fail(reference["path"], "unsupported firmware schema")
        check_schema(document, schema, reference["path"])
        if (
            document["schemaVersion"] != release["schemaVersion"] or
            document["product"] != {"code": binding["productCode"], "key": binding["productKey"]} or
            document["firmware"]["version"] != binding["firmwareVersion"] or
            document["definition"]["revision"] != binding["definitionRevision"] or
            not set(binding["hardwareRevisions"]) <= set(document["compatibility"]["hardwareRevisions"])
        ):
            fail(path, "firmware document disagrees with exact binding")
        content_hash = document["definition"]["contentHash"]
        canonical = json.dumps(
            {field: document[field] for field in content_hash["scope"]},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != content_hash["value"]:
            fail(reference["path"], "firmware definition contentHash is invalid")
        mappings = document["definition"].get("publicationAnimationIds", {})
        if document["schemaVersion"] != 2 or not mappings:
            fail(path, "publication requires a nonempty schema-v2 animation-ID mapping")
        animations = {animation["id"]: animation for animation in document["animations"]}
        if len(animations) != len(document["animations"]):
            fail(reference["path"], "duplicate numeric animation IDs")
        for slug, animation_id in mappings.items():
            check_slug(slug, reference["path"] + ".definition.publicationAnimationIds")
            if type(animation_id) is not int or animation_id not in animations:
                fail(reference["path"], f"publication slug {slug!r} has no exact animation")
        for animation in animations.values():
            if [parameter["index"] for parameter in animation["parameters"]] != list(range(8)):
                fail(reference["path"], "animation must declare all eight ordered parameter slots")
            for parameter in animation["parameters"]:
                allowed_values(parameter, reference["path"])
        self.resolved[key] = document
        return document


def duration_values(firmware, path):
    settings = [setting for setting in firmware["settings"] if setting["index"] == 12]
    if len(settings) != 1:
        fail(path, "automatic duration setting index 12 is missing or ambiguous")
    return {value + 1 for value in allowed_values(settings[0], path)}


def check_playlist(document, firmware, path):
    if len(document["entries"]) > 15:
        fail(path + ".entries", "playlist exceeds 15 entries")
    if document["durationSeconds"] not in duration_values(firmware, path):
        fail(path + ".durationSeconds", "duration is invalid for the exact firmware")
    ids = set()
    mapping = firmware["definition"]["publicationAnimationIds"]
    animations = {animation["id"]: animation for animation in firmware["animations"]}
    for index, entry in enumerate(document["entries"]):
        location = f"{path}.entries[{index}]"
        check_slug(entry["entryId"], location + ".entryId")
        check_slug(entry["animationId"], location + ".animationId")
        if entry["entryId"] in ids:
            fail(location, "duplicate entryId")
        ids.add(entry["entryId"])
        if "label" in entry:
            check_text(entry["label"], location + ".label", 40)
        if entry["animationId"] not in mapping:
            fail(location + ".animationId", "slug is absent from the exact firmware mapping")
        animation = animations[mapping[entry["animationId"]]]
        for slot, value in enumerate(entry["parameters"]):
            if value not in allowed_values(animation["parameters"][slot], location):
                fail(f"{location}.parameters[{slot}]", "value is invalid, including hidden-slot defaults")


def check_migration(document, source, target, path):
    source_ids = source["definition"]["publicationAnimationIds"]
    target_ids = target["definition"]["publicationAnimationIds"]
    mappings = document["animationMappings"]
    if len(mappings) > 256 or len({row["sourceAnimationId"] for row in mappings}) != len(mappings):
        fail(path + ".animationMappings", "duplicate or excessive source mappings")
    if {row["sourceAnimationId"] for row in mappings} != source_ids.keys():
        fail(path + ".animationMappings", "mappings must cover every exact source slug once")
    if len(set(source_ids.values())) != len(source_ids):
        fail(path + ".source", "ambiguous reverse mapping from numeric source IDs")
    source_animations = {animation["id"]: animation for animation in source["animations"]}
    target_animations = {animation["id"]: animation for animation in target["animations"]}
    for index, row in enumerate(mappings):
        location = f"{path}.animationMappings[{index}]"
        check_slug(row["sourceAnimationId"], location)
        check_slug(row["targetAnimationId"], location)
        if row["targetAnimationId"] not in target_ids:
            fail(location, "target slug is absent from the exact target definition")
        before = source_animations[source_ids[row["sourceAnimationId"]]]
        after = target_animations[target_ids[row["targetAnimationId"]]]
        for slot in range(8):
            if not allowed_values(before["parameters"][slot], location) <= allowed_values(
                after["parameters"][slot], location
            ):
                fail(f"{location}.parameters[{slot}]", "target cannot preserve all source values")
    if not duration_values(source, path) <= duration_values(target, path):
        fail(path + ".durationPolicy", "target cannot preserve all source durations")


def git_bytes(root, *arguments):
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, check=False)
    if result.returncode:
        fail("history", result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def check_history(root, base_ref, current, raw):
    if re.fullmatch(r"[0-9a-f]{40}", base_ref) is None:
        fail("history", "--base-ref must be an immutable 40-character commit SHA")
    previous_raw = git_bytes(root, "show", f"{base_ref}:{INDEX}")
    previous = parse_json(previous_raw, "history:" + INDEX, LIMITS["index"])
    if current["indexRevision"] < previous["indexRevision"] or (
        raw != previous_raw and current["indexRevision"] <= previous["indexRevision"]
    ):
        fail(INDEX, "changed index bytes require a strictly higher indexRevision")
    for collection, id_field in (("playlists", "playlistId"), ("migrations", "migrationId")):
        before = {(row[id_field], row["publicationRevision"]): row for row in previous[collection]}
        after = {(row[id_field], row["publicationRevision"]): row for row in current[collection]}
        for identity, old in before.items():
            new = after.get(identity)
            if new is None:
                fail(INDEX, f"published history was removed: {identity}")
            def metadata(row):
                return {key: binding_key(value) if key in ("source", "target") else value
                        for key, value in row.items() if key not in ("status", "withdrawalReason")}
            if metadata(old) != metadata(new):
                fail(INDEX, f"immutable publication metadata changed: {identity}")
            if old["status"] == "withdrawn" and new["status"] != "withdrawn":
                fail(INDEX, f"a withdrawn revision cannot be reactivated: {identity}")
        for identity in after.keys() - before.keys():
            maximum = max((revision for name, revision in before if name == identity[0]), default=0)
            if identity[1] <= maximum:
                fail(INDEX, f"new publication revision must exceed its history: {identity}")
    paths = git_bytes(root, "ls-tree", "-r", "--name-only", base_ref, "--", "playlists", "firmwares")
    for relative in paths.decode("utf-8").splitlines():
        if relative == INDEX or not relative.endswith(".json"):
            continue
        if read_bytes(root, relative) != git_bytes(root, "show", f"{base_ref}:{relative}"):
            fail(relative, "published schema or payload bytes are immutable")


def validate(root, base_ref=None):
    root = Path(root).resolve()
    schema = parse_json(read_bytes(root, "playlists/schema-v1.json"), "playlists/schema-v1.json")
    raw = read_bytes(root, INDEX, LIMITS["index"])
    index = parse_json(raw, INDEX, LIMITS["index"])
    if isinstance(index, dict):
        for collection in ("playlists", "migrations"):
            if isinstance(index.get(collection), list) and len(index[collection]) > 2048:
                fail(INDEX + "." + collection, "record count exceeds 2048")
    check_schema(index, {"$ref": "#/$defs/index", "$defs": schema["$defs"]}, INDEX)
    definitions = FirmwareDefinitions(root)
    counts = {"playlists": 0, "migrations": 0, "withdrawn": 0}
    for collection, kind, id_field in (
        ("playlists", "playlist", "playlistId"), ("migrations", "migration", "migrationId")
    ):
        identities = set()
        for position, row in enumerate(index[collection]):
            path = f"{INDEX}:{collection}[{position}]"
            check_slug(row[id_field], path + "." + id_field)
            identity = (row[id_field], row["publicationRevision"])
            if identity in identities:
                fail(path, "duplicate ID/publicationRevision")
            identities.add(identity)
            prefix = "playlists/" + ("migrations/" if kind == "migration" else "")
            expected = f"{prefix}{identity[0]}/r{identity[1]}.json"
            if row["path"] != expected:
                fail(path + ".path", f"expected canonical path {expected!r}")
            local_path(root, row["path"])
            if not 1 <= row["sizeBytes"] <= LIMITS[kind]:
                fail(path + ".sizeBytes", "declared payload size exceeds its bound")
            check_text(row["name"], path + ".name", 40)
            check_text(row.get("description", ""), path + ".description", 1024, True, False)
            bindings = ("target",) if kind == "playlist" else ("source", "target")
            for field in bindings:
                check_binding(row[field], path + "." + field)
            if kind == "migration":
                source, target = row["source"], row["target"]
                if (source["productCode"], source["productKey"]) != (target["productCode"], target["productKey"]):
                    fail(path, "migration must stay within the same product")
                if version(source["firmwareVersion"], path) >= version(target["firmwareVersion"], path):
                    fail(path, "migration target must be strictly newer")
                if not set(source["hardwareRevisions"]) & set(target["hardwareRevisions"]):
                    fail(path, "migration has no shared hardware revision")
            if row["status"] == "withdrawn":
                check_text(row["withdrawalReason"], path + ".withdrawalReason", 1024, True)
                counts["withdrawn"] += 1
                continue
            if "withdrawalReason" in row:
                fail(path + ".withdrawalReason", "available records cannot have a withdrawal reason")
            payload = read_bytes(root, row["path"], LIMITS[kind])
            if len(payload) != row["sizeBytes"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
                fail(row["path"], "payload size or SHA-256 disagrees with index")
            document = parse_json(payload, row["path"], LIMITS[kind])
            check_schema(document, {"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]}, row["path"])
            for field in (id_field, "publicationRevision", "name", "description", *bindings):
                left, right = document.get(field, ""), row.get(field, "")
                if field in bindings:
                    left, right = binding_key(left), binding_key(right)
                if left != right:
                    fail(row["path"] + "." + field, "payload metadata disagrees with index")
            resolved = [definitions.resolve(row[field], path + "." + field) for field in bindings]
            if kind == "playlist":
                check_playlist(document, resolved[0], row["path"])
            else:
                check_migration(document, *resolved, row["path"])
            counts[collection] += 1
    if base_ref is not None:
        check_history(root, base_ref, index, raw)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-ref", help="immutable base commit for append-only history checks")
    arguments = parser.parse_args()
    try:
        counts = validate(arguments.root, arguments.base_ref)
    except (PublicationError, KeyError, TypeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Validated {counts['playlists']} available playlists and {counts['migrations']} available migrations.")
    print(f"Retained {counts['withdrawn']} withdrawn records as non-executable history; their payloads are not requalified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
