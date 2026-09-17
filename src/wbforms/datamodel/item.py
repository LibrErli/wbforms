from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, constr, model_validator
from pydantic.fields import FieldInfo
from wikibaseintegrator import datatypes
from wikibaseintegrator.wbi_enums import WikibaseSnakType

WIKIBASE_TYPE = "wikibase_type"
WIKIBASE_ID = "WIKIBASE_ID"
WIKIDATA_ID = "WIKIDATA_ID"


class _EmptyStringsMixin(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _coerce_empty_strings(cls, data):
        if not isinstance(data, dict):
            return data
        cleaned = {}
        for k, v in data.items():
            if v == "":
                cleaned[k] = None
            elif isinstance(v, list):
                cleaned[k] = [x for x in v if x != "" and x is not None]
            else:
                cleaned[k] = v
        return cleaned


class ItemBase(_EmptyStringsMixin):
    """
    Wikibase item model
    """

    qid: Annotated[
        str | None,
        Field(
            description="Qid of the paper",
            pattern=r"Q\d+",
            json_schema_extra={WIKIBASE_ID: "rdf:subject"},
        ),
    ] = None


class EntityBase(_EmptyStringsMixin):
    label: Annotated[str, Field(json_schema_extra={WIKIBASE_ID: "rdfs:label"})]
    description: Annotated[str, Field(json_schema_extra={WIKIBASE_ID: "schema:description"})]


class StatementBase(_EmptyStringsMixin):
    @classmethod
    def get_statement_subject(cls, lookup_key: str) -> str:
        """
        Each statement is expected to have one field as the statement subject.
        :return:
        """
        field_name: str
        field_metadata: FieldInfo
        subject_field = None
        for field_name, field_metadata in cls.model_fields.items():
            extra = field_metadata.json_schema_extra
            if not isinstance(extra, dict):
                continue
            field_prop_id = extra.get(lookup_key)
            if field_prop_id is not None:
                id_parts = field_prop_id.split("/")
                if len(id_parts) > 2 and id_parts[-2] == "statement":
                    subject_field = field_name
                    break
        if subject_field is None:
            raise Exception(f"Model {cls.__name__} has no statement object defined for {lookup_key}")
        return subject_field

    @classmethod
    def get_qualifier_fields(cls, lookup_key: str) -> list[str]:
        """
        Get fields that are stored as statement qualifier
        :param lookup_key:
        :return:
        """
        field_name: str
        field_metadata: FieldInfo
        qualifier_fields: list[str] = []
        for field_name, field_metadata in cls.model_fields.items():
            extra = field_metadata.json_schema_extra
            if not isinstance(extra, dict):
                continue
            field_prop_id = extra.get(lookup_key)
            if field_prop_id is not None:
                id_parts = field_prop_id.split("/")
                if len(id_parts) > 2 and id_parts[-2] == "qualifier":
                    qualifier_fields.append(field_name)
        return qualifier_fields


class Statement(StatementBase):
    statement_id: Annotated[str, Field(pattern=r"Q\d+", json_schema_extra={WIKIBASE_ID: "rdf:subject"})]


class ExtractedStatement(StatementBase):
    """
    Statement which is extracted and thus has the object named as qualifier set
    The extracted value field is optional to be compatible to already existing entries
    """

    object_named_as: Annotated[
        str | None,
        Field(
            json_schema_extra={
                WIKIBASE_ID: "https://ceur-dev.wikibase.cloud/prop/qualifier/P91",
                WIKIBASE_TYPE: datatypes.String.DTYPE,
            }
        ),
    ] = None

    @model_validator(mode="after")
    def validate_object_named_as(self) -> Self:
        """
        Check if the object_named_as field must be set
        """
        statement_object_field = self.get_statement_subject(WIKIBASE_ID)
        statement_object_value = getattr(self, statement_object_field)
        if statement_object_value == WikibaseSnakType.UNKNOWN_VALUE.value and self.object_named_as is None:
            raise ValueError(
                f"If the statement object field {statement_object_field} is set as unknown value the object_named_as "
                f"field must be set."
            )
        return self

    def __eq__(self, other):
        other_object_named_as = getattr(other, "object_named_as", None)
        if None in [self.object_named_as, other_object_named_as]:
            if isinstance(other, str):
                return False
            stmt_object_field = self.get_statement_subject(WIKIBASE_ID)
            return getattr(self, stmt_object_field) == getattr(other, stmt_object_field)
        else:
            return self.object_named_as == other_object_named_as


ItemStatementSubjectType = Literal["somevalue", "novalue"] | constr(pattern=r"^Q\d+$")


class WikibaseReferenceBase(_EmptyStringsMixin):
    """
    One Wikibase statement-level reference block: a group of property/value snaks
    documenting the provenance of a statement.
    """

    @classmethod
    def get_reference_fields(cls, lookup_key: str) -> list[str]:
        """
        Get fields stored inside a Wikibase reference block. A field qualifies
        when its property URL has the path segment ``/reference/Pxx``.
        """
        field_name: str
        field_metadata: FieldInfo
        reference_fields: list[str] = []
        for field_name, field_metadata in cls.model_fields.items():
            extra = field_metadata.json_schema_extra
            if not isinstance(extra, dict):
                continue
            field_prop_id = extra.get(lookup_key)
            if field_prop_id is not None:
                id_parts = field_prop_id.split("/")
                if len(id_parts) > 2 and id_parts[-2] == "reference":
                    reference_fields.append(field_name)
        return reference_fields


class Coordinate(BaseModel):
    longitude: float
    latitude: float
