"""Tests for default_value annotation support in Pydantic model generation.

This test suite verifies that:
1. default_value annotations in LinkML schema slot_usage are properly read
2. They are included in json_schema_extra of generated Pydantic models
3. They are used as actual field defaults
4. They are available in JSON schema for API/JS frontend consumption

To run this test file directly: python3 tests/codegen/test_pydantic_gen_default_value.py
"""

import sys
from pathlib import Path

# Add src directory to Python path for direct execution
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from pydantic.fields import FieldInfo

from wbforms.codegen.pydantic_gen import generate_models


_SCHEMA_WITH_DEFAULT_VALUE = """
id: https://example.org/schema/test-default-value
name: test_default_value

description: Test schema for default_value annotation support

prefixes:
  linkml: https://w3id.org/linkml/

default_range: string

imports:
  - linkml:types

slots:
  instance_of:
    range: string
    annotations:
      wikibase_id: "https://example.org/prop/direct/P2"
      wikibase_type: item
  custom_field:
    range: string
    annotations:
      wikibase_id: "https://example.org/prop/direct/P3"
      wikibase_type: string

classes:
  TestEntity:
    annotations:
      python_base: entity_item
    slots:
      - instance_of
      - custom_field
    slot_usage:
      instance_of:
        annotations:
          default_value: Q24499
  
  AnotherEntity:
    annotations:
      python_base: entity_item
    slots:
      - instance_of
      - custom_field
    slot_usage:
      instance_of:
        annotations:
          default_value: Q12345
      custom_field:
        annotations:
          default_value: "Some default value"
"""


@pytest.fixture
def schema_path(tmp_path: Path) -> Path:
    """Create a temporary schema file with default_value annotations."""
    path = tmp_path / "test_default_value_schema.yaml"
    path.write_text(_SCHEMA_WITH_DEFAULT_VALUE, encoding="utf-8")
    return path


@pytest.fixture
def models(schema_path: Path) -> dict[str, type]:
    """Generate models from the test schema."""
    return generate_models(schema_path)


class TestDefaultValueInFieldDef:
    """Test that default_value is properly set in Pydantic field definitions."""

    def test_default_value_in_json_schema_extra(self, models: dict[str, type]):
        """default_value annotation appears in json_schema_extra."""
        test_entity_base = models["TestEntityBase"]
        instance_of_field: FieldInfo = test_entity_base.model_fields["instance_of"]

        assert "default_value" in instance_of_field.json_schema_extra
        assert instance_of_field.json_schema_extra["default_value"] == "Q24499"

    def test_default_value_as_field_default(self, models: dict[str, type]):
        """default_value annotation is used as the actual field default."""
        test_entity_base = models["TestEntityBase"]
        instance_of_field: FieldInfo = test_entity_base.model_fields["instance_of"]

        # For optional fields, default_value should be the field default
        assert instance_of_field.default == "Q24499"

    def test_multiple_default_values_in_same_class(self, models: dict[str, type]):
        """Multiple fields in the same class can have different default_values."""
        another_entity_base = models["AnotherEntityBase"]
        
        instance_of_field: FieldInfo = another_entity_base.model_fields["instance_of"]
        custom_field: FieldInfo = another_entity_base.model_fields["custom_field"]

        # Each field has its own default_value
        assert instance_of_field.json_schema_extra["default_value"] == "Q12345"
        assert instance_of_field.default == "Q12345"
        
        assert custom_field.json_schema_extra["default_value"] == "Some default value"
        assert custom_field.default == "Some default value"

    def test_default_value_in_create_model(self, models: dict[str, type]):
        """default_value works in Create models (for optional fields)."""
        test_entity_create = models["TestEntityCreate"]
        instance_of_field: FieldInfo = test_entity_create.model_fields["instance_of"]

        # In Create model, the default should still be set
        assert instance_of_field.default == "Q24499"
        assert instance_of_field.json_schema_extra["default_value"] == "Q24499"

    def test_default_value_in_read_model(self, models: dict[str, type]):
        """default_value is available in read (lenient) models."""
        test_entity = models["TestEntity"]
        instance_of_field: FieldInfo = test_entity.model_fields["instance_of"]

        # In read model, the default should be set (lenient models make required fields optional)
        assert instance_of_field.default == "Q24499"
        assert instance_of_field.json_schema_extra["default_value"] == "Q24499"


class TestDefaultValueInJsonSchema:
    """Test that default_value is available in the JSON schema for API consumers."""

    def test_default_value_in_model_json_schema(self, models: dict[str, type]):
        """default_value appears in the model's JSON schema."""
        test_entity_base = models["TestEntityBase"]
        schema = test_entity_base.model_json_schema()
        
        instance_of_props = schema["properties"]["instance_of"]
        
        # default_value should be in the JSON schema properties
        assert "default_value" in instance_of_props
        assert instance_of_props["default_value"] == "Q24499"

    def test_wikibase_metadata_preserved(self, models: dict[str, type]):
        """Original wikibase metadata is still present alongside default_value."""
        test_entity_base = models["TestEntityBase"]
        schema = test_entity_base.model_json_schema()
        
        instance_of_props = schema["properties"]["instance_of"]
        
        # Original metadata should still be there
        assert "WIKIBASE_ID" in instance_of_props
        assert instance_of_props["WIKIBASE_ID"] == "https://example.org/prop/direct/P2"
        assert "wikibase_type" in instance_of_props
        assert instance_of_props["wikibase_type"] == "wikibase-item"
        
        # And default_value should also be there
        assert "default_value" in instance_of_props


class TestDefaultValueUsage:
    """Test that default_value actually works when creating model instances."""

    def test_model_instance_uses_default(self, models: dict[str, type]):
        """Creating a model instance without specifying a field uses the default_value."""
        another_entity_base = models["AnotherEntityBase"]
        
        # Create instance without specifying instance_of or custom_field
        # Note: label and description are required from EntityBase, so we need to provide them
        instance = another_entity_base(label="Test Label", description="Test Desc")
        
        # instance_of and custom_field should have their default values
        assert instance.instance_of == "Q12345"
        assert instance.custom_field == "Some default value"

    def test_model_instance_can_override_default(self, models: dict[str, type]):
        """Creating a model instance can override the default_value."""
        another_entity_base = models["AnotherEntityBase"]
        
        # Create instance with explicit instance_of and custom_field
        instance = another_entity_base(
            label="Test Label", 
            description="Test Desc",
            instance_of="Q99999",
            custom_field="Overridden value"
        )
        
        # instance_of and custom_field should be the overridden values
        assert instance.instance_of == "Q99999"
        assert instance.custom_field == "Overridden value"

    def test_model_dump_includes_default(self, models: dict[str, type]):
        """Model dump includes fields with default values."""
        another_entity_base = models["AnotherEntityBase"]
        
        instance = another_entity_base(label="Test Label", description="Test Desc")
        dumped = instance.model_dump()
        
        assert dumped["label"] == "Test Label"
        assert dumped["description"] == "Test Desc"
        assert dumped["instance_of"] == "Q12345"
        assert dumped["custom_field"] == "Some default value"


class TestBackwardCompatibility:
    """Test that existing functionality is not broken."""

    def test_fields_without_default_value_still_work(self, schema_path: Path, models: dict[str, type]):
        """Fields without default_value annotations still work as before."""
        # Create a schema without default_value
        simple_schema = """
id: https://example.org/schema/test-simple
name: test_simple
slots:
  simple_slot:
    range: string
    annotations:
      wikibase_id: "https://example.org/prop/direct/P1"
      wikibase_type: string

classes:
  SimpleEntity:
    annotations:
      python_base: entity_item
    slots:
      - simple_slot
"""
        simple_path = schema_path.parent / "simple_schema.yaml"
        simple_path.write_text(simple_schema, encoding="utf-8")
        simple_models = generate_models(simple_path)
        
        simple_entity_base = simple_models["SimpleEntityBase"]
        simple_slot_field: FieldInfo = simple_entity_base.model_fields["simple_slot"]
        
        # Should have standard wikibase metadata
        assert "WIKIBASE_ID" in simple_slot_field.json_schema_extra
        assert "wikibase_type" in simple_slot_field.json_schema_extra
        
        # Should NOT have default_value (since it wasn't specified)
        assert "default_value" not in simple_slot_field.json_schema_extra
        
        # Default should be None for optional fields without default_value
        assert simple_slot_field.default is None


if __name__ == "__main__":
    import subprocess
    import sys
    
    # Run pytest on this file
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v"],
        cwd=str(Path(__file__).parent.parent.parent),
    )
    sys.exit(result.returncode)
