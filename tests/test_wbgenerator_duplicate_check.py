"""In-memory tests for the duplicate check in add_statement_from_model.

The check must compare the full statement content (subject *and* qualifiers),
not just the statement subject: adding an extracted statement whose subject is
already present but whose qualifiers differ (e.g. begin_date/end_date) must be
allowed, while a statement identical in subject and qualifiers must be rejected.

No Wikibase network calls are made.
"""

import unittest

from wikibaseintegrator.entities import ItemEntity

from wbforms.codegen import get_models
from wbforms.wbgenerator import (
    add_statement_from_model,
    create_qualified_statement_from_model,
    get_item_statement_by_model,
)


class TestDuplicateCheckWithQualifiers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = get_models()
        cls.Create = m["ScholarSignatureCreate"]
        cls.Read = m["ScholarSignature"]

    def _item_with_statement(self, **create_kwargs) -> ItemEntity:
        sig = self.Create(**create_kwargs)
        claim = create_qualified_statement_from_model(sig)
        item = ItemEntity()
        item.id = "Q1"
        item.claims.add(claim)
        return item

    def _claim_count(self, item: ItemEntity) -> int:
        # scholar_id is the statement subject of ScholarSignature (prop/statement/P93)
        return len(item.claims.get("P93"))

    def test_same_subject_different_qualifiers_is_not_a_duplicate(self):
        """User scenario: statement exists without qualifiers, new one has qualifiers set."""
        item = self._item_with_statement(scholar_id="Q42")
        add_statement_from_model(item, self.Create(scholar_id="Q42", series_ordinal=1))
        self.assertEqual(self._claim_count(item), 2)

    def test_same_subject_different_qualifier_values_is_not_a_duplicate(self):
        item = self._item_with_statement(scholar_id="Q42", series_ordinal=1, affiliation=["Q1"])
        add_statement_from_model(item, self.Create(scholar_id="Q42", series_ordinal=2, affiliation=["Q9"]))
        self.assertEqual(self._claim_count(item), 2)

    def test_identical_subject_and_qualifiers_raises(self):
        item = self._item_with_statement(scholar_id="Q42", series_ordinal=1, affiliation=["Q1"])
        with self.assertRaises(ValueError) as ctx:
            add_statement_from_model(item, self.Create(scholar_id="Q42", series_ordinal=1, affiliation=["Q1"]))
        self.assertIn("Statement already exists", str(ctx.exception))
        self.assertEqual(self._claim_count(item), 1)

    def test_identical_subject_without_qualifiers_raises(self):
        item = self._item_with_statement(scholar_id="Q42")
        with self.assertRaises(ValueError):
            add_statement_from_model(item, self.Create(scholar_id="Q42"))

    def test_multivalue_qualifier_match_is_order_insensitive(self):
        item = self._item_with_statement(scholar_id="Q42", affiliation=["Q1", "Q2"])
        with self.assertRaises(ValueError):
            add_statement_from_model(item, self.Create(scholar_id="Q42", affiliation=["Q2", "Q1"]))

    def test_multivalue_qualifier_different_values_is_not_a_duplicate(self):
        item = self._item_with_statement(scholar_id="Q42", affiliation=["Q1", "Q2"])
        add_statement_from_model(item, self.Create(scholar_id="Q42", affiliation=["Q1", "Q3"]))
        self.assertEqual(self._claim_count(item), 2)

    def test_get_item_statement_by_model_match_qualifiers(self):
        item = self._item_with_statement(scholar_id="Q42", series_ordinal=1)
        add_statement_from_model(item, self.Create(scholar_id="Q42", series_ordinal=2))
        # subject-only match (default) still finds a statement
        self.assertIsNotNone(get_item_statement_by_model(item, self.Create(scholar_id="Q42")))
        # exact match distinguishes the qualifiers
        exact = get_item_statement_by_model(
            item, self.Create(scholar_id="Q42", series_ordinal=2), match_qualifiers=True
        )
        self.assertIsNotNone(exact)
        self.assertEqual(exact.series_ordinal, 2)
        self.assertIsNone(
            get_item_statement_by_model(item, self.Create(scholar_id="Q42", series_ordinal=5), match_qualifiers=True)
        )


if __name__ == "__main__":
    unittest.main()
