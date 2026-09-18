import unittest

from wikibaseintegrator.wbi_enums import WikibaseSnakType

from wbforms.codegen import SubjectBase


class TestExtractedStatement(unittest.TestCase):
    def test_object_named_as_required(self):
        """
        tests if object_named_as is required if the statement object is unknown
        
        NOTE: This test is now obsolete. The object_named_as validation is no longer
        in the ExtractedStatement base class. It should be handled by:
        1. Frontend validation via enforce_unknown_stmt_name flag
        2. Dynamic validation in generated classes (if needed in the future)
        
        The field is now only present if explicitly defined in the schema.
        """
        # Skip this test as it tests removed functionality
        self.skipTest("object_named_as validation moved to schema-defined classes")

    def test_equivalence(self):
        """
        Test equivalence of statement objects with object_named_as.
        
        NOTE: This test is now obsolete. The __eq__ method is no longer customized
        in ExtractedStatement base class. The default Pydantic __eq__ is used now.
        
        The field is now only present if explicitly defined in the schema.
        """
        # Skip this test as it tests removed functionality
        self.skipTest("Custom __eq__ removed from ExtractedStatement base class")


if __name__ == "__main__":
    unittest.main()
