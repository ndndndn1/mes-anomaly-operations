import unittest
from operations.control.manifest import Manifest, LABEL
from operations.control.preflight import inspect

BASE = {
    "installation": "reference-test",
    "application_image": "sha256:" + "a" * 64,
    "database_image": "sha256:" + "b" * 64,
    "cache_image": "sha256:" + "c" * 64,
}


class Inventory:
    def resources(self):
        return {
            "memory_available_bytes": 4 * 1024**3,
            "storage_available_bytes": 4 * 1024**3,
            "cpus": 2,
        }

    def image(self, ref):
        return {
            "Id": ref,
            "Architecture": "amd64",
            "Config": {"Env": ["PASSWORD=not-for-output", "PG_MAJOR=17"]},
        }

    def container(self, name):
        return None


class Contract(unittest.TestCase):
    def test_insufficient_capacity_refuses_installation(self):
        class LowMemory(Inventory):
            def resources(self):
                return {
                    "memory_available_bytes": 1024,
                    "storage_available_bytes": 4 * 1024**3,
                    "cpus": 2,
                }

        result = inspect(Manifest.parse(BASE), LowMemory())
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"][0]["ok"])

    def test_database_image_major_missing_wrong_or_ambiguous_refused(self):
        for declared in [[], ["PG_MAJOR=18"], ["PG_MAJOR=17", "PG_MAJOR=18"]]:
            with self.subTest(declared=declared):

                class WrongEngine(Inventory):
                    def image(self, ref):
                        image = super().image(ref)
                        if ref == BASE["database_image"]:
                            image["Config"]["Env"] = declared
                        return image

                result = inspect(Manifest.parse(BASE), WrongEngine())
                self.assertFalse(result["ok"])
                self.assertFalse(
                    next(
                        x
                        for x in result["checks"]
                        if x["check"] == "database.image_major"
                    )["ok"]
                )

    def test_mutable_tag_refused(self):
        with self.assertRaises(ValueError):
            Manifest.parse({**BASE, "application_image": "app:latest"})

    def test_unknown_fields_refused(self):
        with self.assertRaises(ValueError):
            Manifest.parse({**BASE, "force": True})

    def test_timeout_bool_refused(self):
        with self.assertRaises(ValueError):
            Manifest.parse({**BASE, "drain_seconds": True})

    def test_shell_like_identity_refused(self):
        with self.assertRaises(ValueError):
            Manifest.parse({**BASE, "installation": "a;echo x"})

    def test_foreign_container_blocks(self):
        class Foreign(Inventory):
            def container(self, name):
                return {"Config": {"Labels": {LABEL: "another"}}}

        self.assertFalse(inspect(Manifest.parse(BASE), Foreign())["ok"])

    def test_failure_is_not_absence(self):
        class Failure(Inventory):
            def container(self, name):
                raise RuntimeError("engine unavailable")

        result = inspect(Manifest.parse(BASE), Failure())
        self.assertFalse(result["ok"])
        self.assertEqual(sum(not x["ok"] for x in result["checks"]), 3)

    def test_inspect_redacts_environment(self):
        result = inspect(Manifest.parse(BASE), Inventory())
        self.assertTrue(result["ok"])
        self.assertNotIn("PASSWORD", str(result))

    def test_managed_identity_allowed(self):
        class Managed(Inventory):
            def container(self, name):
                return {"Config": {"Labels": {LABEL: "reference-test"}}}

        self.assertTrue(inspect(Manifest.parse(BASE), Managed())["ok"])


if __name__ == "__main__":
    unittest.main()
