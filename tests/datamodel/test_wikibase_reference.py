"""Unit tests for the WikibaseReference codegen output and opt-in mechanism."""

import unittest

from wbforms.codegen import get_models
from wbforms.datamodel.item import WIKIBASE_ID


class TestWikibaseReferenceModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = get_models()
        cls.WikibaseReference = cls.models["WikibaseReference"]

    def test_wikibase_reference_fields(self):
        """WikibaseReference exposes the three configured slots."""
        self.assertEqual(
            sorted(self.WikibaseReference.model_fields.keys()),
            ["reference_url", "retrieved", "stated_in"],
        )

    def test_get_reference_fields_identifies_all(self):
        """get_reference_fields() returns every slot annotated with /reference/Pxx."""
        self.assertEqual(
            sorted(self.WikibaseReference.get_reference_fields(WIKIBASE_ID)),
            ["reference_url", "retrieved", "stated_in"],
        )

    def test_property_ids_are_reference_path(self):
        """Each slot uses the /reference/ path segment, not /qualifier/ or /statement/."""
        for fname in self.WikibaseReference.get_reference_fields(WIKIBASE_ID):
            prop_url = self.WikibaseReference.model_fields[fname].json_schema_extra[WIKIBASE_ID]
            self.assertIn("/reference/", prop_url, f"{fname} should use /reference/ path")


class TestSourcesFieldInjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = get_models()

    def test_opted_in_classes_have_sources(self):
        """ScholarSignature, Subject and EditorSignature opt in via supports_references."""
        for class_name in ("ScholarSignature", "Subject", "EditorSignature"):
            with self.subTest(class_name=class_name):
                cls = self.models[class_name]
                self.assertIn("sources", cls.model_fields)

    def test_non_opted_in_class_has_no_sources(self):
        """The bibliographic Reference class does not opt in and stays clean."""
        # Reference (bibliographic) is a statement class but never sets supports_references
        self.assertNotIn("sources", self.models["Reference"].model_fields)

    def test_sources_default_is_empty_list(self):
        """Creating a statement without sources gives an empty list, not None."""
        ScholarSignatureCreate = self.models["ScholarSignatureCreate"]
        sig = ScholarSignatureCreate(scholar_id="Q1")
        self.assertEqual(sig.sources, [])


if __name__ == "__main__":
    unittest.main()
