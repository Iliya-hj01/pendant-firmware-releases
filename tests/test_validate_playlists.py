import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_playlists", ROOT / "scripts" / "validate_playlists.py")
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class PublicationValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        commit = "412f218da64adfd3f09f91e274b47eb7ce263fb3"
        paths = validator.git_bytes(ROOT, "ls-tree", "-r", "--name-only", commit, "--", "playlists")
        relatives = [path for path in paths.decode().splitlines() if path.endswith(".json")]
        relatives += [
            "lilum-firmware-catalogue.json", "lilum-firmware-definition.json",
            "firmwares/mandalum/lilum-mandalum-firmware-v1.0.7.json",
            "firmwares/mandalum/lilum-mandalum-firmware-v1.0.8.json",
        ]
        cls.fixtures = {path: validator.git_bytes(ROOT, "show", f"{commit}:{path}") for path in relatives}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for relative, raw in self.fixtures.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        index = self.read(validator.INDEX)
        index["indexRevision"] = 6
        index["migrations"][0].update(status="withdrawn", withdrawalReason="Incomplete source-slug coverage.")
        self.write(validator.INDEX, index)

    def read(self, relative):
        return json.loads((self.root / relative).read_bytes())

    def write(self, relative, document):
        raw = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()
        (self.root / relative).write_bytes(raw)
        return raw

    def change_index(self, change):
        index = self.read(validator.INDEX)
        change(index)
        self.write(validator.INDEX, index)

    def change_payload(self, collection, position, change):
        index = self.read(validator.INDEX)
        record = index[collection][position]
        document = self.read(record["path"])
        change(document)
        raw = self.write(record["path"], document)
        record.update(sizeBytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.write(validator.INDEX, index)

    def rejected(self, expression):
        with self.assertRaisesRegex(validator.PublicationError, expression):
            validator.validate(self.root)

    def test_real_available_publications_and_withdrawn_history(self):
        self.assertEqual(
            {"playlists": 4, "migrations": 1, "withdrawn": 2},
            validator.validate(self.root),
        )

    def test_independent_repeated_entries_and_omitted_optional_fields(self):
        def mutate(document):
            duplicate = copy.deepcopy(document["entries"][0])
            duplicate["entryId"] = "independent-duplicate"
            duplicate.pop("label", None)
            document["entries"].append(duplicate)
        self.change_payload("playlists", 1, mutate)
        self.assertEqual(4, validator.validate(self.root)["playlists"])

    def test_missing_optional_description_is_valid(self):
        index = self.read(validator.INDEX)
        record = index["playlists"][1]
        record.pop("description")
        document = self.read(record["path"])
        document.pop("description")
        raw = self.write(record["path"], document)
        record.update(sizeBytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.write(validator.INDEX, index)
        validator.validate(self.root)

    def test_duplicate_keys_bom_utf8_trailing_content_and_numeric_coercions(self):
        cases = {
            "duplicate-key": b'{"a":1,"a":2}',
            "bom": b"\xef\xbb\xbf{}",
            "malformed-utf8": b"\xc3(",
            "trailing-content": b"{}{}",
            "decimal": b'{"value":1.0}',
            "exponent": b'{"value":1e0}',
            "nonfinite": b'{"value":NaN}',
            "integer-overflow": b'{"value":9223372036854775808}',
            "unpaired-surrogate": b'{"value":"\\ud800"}',
        }
        for name, raw in cases.items():
            with self.subTest(name=name), self.assertRaises(validator.PublicationError):
                validator.parse_json(raw, name)

    def test_byte_and_nesting_limits(self):
        with self.assertRaisesRegex(validator.PublicationError, "exceeds"):
            validator.parse_json(b" " * (validator.LIMITS["index"] + 1), "index", validator.LIMITS["index"])
        with self.assertRaisesRegex(validator.PublicationError, "nesting"):
            validator.parse_json(b"[" * 33 + b"0" + b"]" * 33, "nested")

    def test_paths_reject_traversal_encoding_and_external_sources(self):
        for path in ("../escape", "/absolute", "playlists/../escape", "playlists/%2e/file",
                     "https://example.invalid/file", "playlists\\file", "playlists//file"):
            with self.subTest(path=path), self.assertRaises(validator.PublicationError):
                validator.local_path(self.root, path)

    def test_unknown_fields_and_boolean_integer_are_rejected(self):
        self.change_index(lambda index: index.update(future=True))
        self.rejected("Additional properties")
        index = self.read(validator.INDEX)
        index.pop("future")
        index["indexRevision"] = True
        self.write(validator.INDEX, index)
        self.rejected("not of type")

    def test_index_count_bound(self):
        self.change_index(lambda index: index.update(playlists=[None] * 2049))
        self.rejected("record count")

    def test_duplicate_revision_identity(self):
        self.change_index(lambda index: index["playlists"].append(copy.deepcopy(index["playlists"][0])))
        self.rejected("duplicate ID")

    def test_invalid_slug_and_noncanonical_revision_path(self):
        self.change_index(lambda index: index["playlists"][0].update(path="playlists/wrong/r1.json"))
        self.rejected("canonical path")
        self.change_index(lambda index: index["playlists"][0].update(playlistId="bad--slug"))
        self.rejected("does not match")

    def test_exact_firmware_binding_and_checksum_are_required(self):
        self.change_index(lambda index: index["playlists"][1]["target"].update(definitionRevision=99))
        self.rejected("payload metadata")

    def test_firmware_integrity_is_checked_before_definition_use(self):
        path = self.root / "firmwares" / "mandalum" / "lilum-mandalum-firmware-v1.0.8.json"
        path.write_bytes(path.read_bytes() + b"\n")
        self.rejected("firmware size or SHA-256")

    def test_playlist_integrity_is_checked_before_parsing(self):
        index = self.read(validator.INDEX)
        path = self.root / index["playlists"][1]["path"]
        path.write_bytes(path.read_bytes() + b"\n")
        self.rejected("payload size or SHA-256")

    def test_metadata_mismatch_is_not_silently_adopted(self):
        self.change_payload("playlists", 1, lambda document: document.update(name="Changed"))
        self.rejected("payload metadata")

    def test_duplicate_entry_ids_and_capacity_limit(self):
        self.change_payload("playlists", 1, lambda document: document["entries"].append(document["entries"][0]))
        self.rejected("duplicate entryId")
        self.change_payload("playlists", 1, lambda document: document.update(entries=document["entries"] * 3))
        self.rejected("exceeds 15")

    def test_missing_animation_mapping_blocks_import(self):
        self.change_payload("playlists", 1, lambda document: document["entries"][0].update(animationId="unknown"))
        self.rejected("absent from the exact")

    def test_hidden_slot_defaults_and_parameter_domains(self):
        def mutate(document):
            document["entries"][0]["parameters"][7] = 1
        self.change_payload("playlists", 1, mutate)
        self.rejected("hidden-slot defaults")

    def test_duration_and_label_boundaries(self):
        self.change_payload("playlists", 1, lambda document: document.update(durationSeconds=257))
        self.rejected("greater than the maximum")
        self.change_payload("playlists", 1, lambda document: document.update(durationSeconds=256))
        validator.validate(self.root)
        self.change_payload("playlists", 1, lambda document: document["entries"][0].update(label=None))
        self.rejected("not of type")

    def test_missing_duplicate_and_unknown_source_mapping(self):
        self.change_payload("migrations", 2, lambda document: document["animationMappings"].pop())
        self.rejected("every exact source slug")
        self.change_payload("migrations", 2, lambda document: document["animationMappings"].append(
            copy.deepcopy(document["animationMappings"][0])))
        self.rejected("duplicate or excessive")

    def test_unavailable_mapping_target(self):
        self.change_payload("migrations", 2, lambda document: document["animationMappings"][0].update(
            targetAnimationId="unknown"))
        self.rejected("target slug")

    def test_changed_numeric_target_ids_use_the_exact_target_map(self):
        source = self.read("firmwares/mandalum/lilum-mandalum-firmware-v1.0.7.json")
        target = self.read("firmwares/mandalum/lilum-mandalum-firmware-v1.0.8.json")
        migration = self.read("playlists/migrations/mandalum-1-0-7-to-1-0-8/r3.json")
        target["animations"][0]["id"] = 100
        target["definition"]["publicationAnimationIds"]["rainbow-cycle"] = 100
        validator.check_migration(migration, source, target, "changed-ids")

    def test_target_cannot_silently_clamp_parameters_or_duration(self):
        source = self.read("firmwares/mandalum/lilum-mandalum-firmware-v1.0.7.json")
        target = self.read("firmwares/mandalum/lilum-mandalum-firmware-v1.0.8.json")
        migration = self.read("playlists/migrations/mandalum-1-0-7-to-1-0-8/r3.json")
        target["animations"][0]["parameters"][0]["minimum"] = 1
        with self.assertRaisesRegex(validator.PublicationError, "preserve all source values"):
            validator.check_migration(migration, source, target, "invalid-target")
        target["animations"][0]["parameters"][0]["minimum"] = 0
        target["settings"][12]["maximum"] = 254
        with self.assertRaisesRegex(validator.PublicationError, "preserve all source durations"):
            validator.check_migration(migration, source, target, "invalid-duration")

    def test_nonpreserve_policy_and_downloaded_operations_are_forbidden(self):
        self.change_payload("migrations", 2, lambda document: document.update(parameterPolicy="reset"))
        self.rejected("'preserve' was expected")
        self.change_payload("migrations", 2, lambda document: document.update(
            parameterPolicy="preserve", rules=[]))
        self.rejected("Additional properties")

    def test_incomplete_older_migration_must_be_withdrawn_not_ignored(self):
        self.change_index(lambda index: index["migrations"][0].update(status="available"))
        self.change_index(lambda index: index["migrations"][0].pop("withdrawalReason"))
        self.rejected("every exact source slug")

    def test_withdrawn_artifacts_are_excluded_but_require_nonblank_reason(self):
        self.change_index(lambda index: index["migrations"][1].update(withdrawalReason=" "))
        self.rejected("text must contain")

    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.root), *arguments]).decode().strip()

    def history_baseline(self):
        self.git("init", "--quiet")
        self.git("config", "user.name", "Publication tests")
        self.git("config", "user.email", "publication-tests@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Synthetic publication-test baseline")
        return self.git("rev-parse", "HEAD")

    def test_history_rejects_changed_equal_index_and_allows_unchanged(self):
        base = self.history_baseline()
        validator.validate(self.root, base)
        path = self.root / validator.INDEX
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(validator.PublicationError, "strictly higher"):
            validator.validate(self.root, base)

    def test_history_rejects_deleted_rows(self):
        base = self.history_baseline()
        self.change_index(lambda index: index.update(indexRevision=index["indexRevision"] + 1))
        self.change_index(lambda index: index["migrations"].pop())
        with self.assertRaisesRegex(validator.PublicationError, "history was removed"):
            validator.validate(self.root, base)

    def test_history_rejects_reactivation_of_a_valid_withdrawn_revision(self):
        self.change_index(lambda index: index["migrations"][2].update(
            status="withdrawn", withdrawalReason="Test withdrawal."))
        base = self.history_baseline()
        def mutate(index):
            index["indexRevision"] += 1
            index["migrations"][2]["status"] = "available"
            index["migrations"][2].pop("withdrawalReason")
        self.change_index(mutate)
        with self.assertRaisesRegex(validator.PublicationError, "cannot be reactivated"):
            validator.validate(self.root, base)

    def test_history_rejects_backfilled_lower_revisions(self):
        index = self.read(validator.INDEX)
        removed = index["playlists"].pop(1)
        self.write(validator.INDEX, index)
        base = self.history_baseline()
        index["indexRevision"] += 1
        index["playlists"].append(removed)
        self.write(validator.INDEX, index)
        with self.assertRaisesRegex(validator.PublicationError, "must exceed its history"):
            validator.validate(self.root, base)

    def test_history_protects_withdrawn_payload_bytes(self):
        base = self.history_baseline()
        index = self.read(validator.INDEX)
        path = self.root / index["migrations"][1]["path"]
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(validator.PublicationError, "bytes are immutable"):
            validator.validate(self.root, base)

    def test_history_rejects_mutated_metadata_even_for_withdrawn_rows(self):
        base = self.history_baseline()
        def mutate(index):
            index["indexRevision"] += 1
            index["migrations"][1]["sha256"] = "0" * 64
        self.change_index(mutate)
        with self.assertRaisesRegex(validator.PublicationError, "immutable publication metadata"):
            validator.validate(self.root, base)


if __name__ == "__main__":
    unittest.main()
