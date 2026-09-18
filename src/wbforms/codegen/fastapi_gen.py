"""Generate FastAPI routers from the endpoint definitions derived from the LinkML schema."""

from inspect import Parameter, Signature
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from pydantic import Field
from starlette import status

from wbforms.api.auth import get_current_user
from wbforms.api.utils import (
    handle_get_all_statements,
    handle_get_item_by_id,
    handle_get_statement_by_id,
    handle_item_creation,
    handle_item_deletion,
    handle_item_update,
    handle_statement_creation,
    handle_statement_deletion_by_id,
    handle_statement_deletion_by_object,
    handle_statement_update,
)
from wbforms.codegen.endpoints import derive_endpoints
from wbforms.session import WikibaseSession

_QID = Annotated[str, Field(pattern=r"Q\d+")]
_AUTH = Annotated[WikibaseSession, Depends(get_current_user)]
_REASON = Annotated[str | None, Field(description="Reason for deletion")]


def _make_handler(params: list[tuple], fn: Any) -> Any:
    """
    Wrap *fn* (which accepts **kwargs) in a new callable that exposes a custom
    __signature__ FastAPI can introspect for path/query/body/dependency resolution.

    Each element of *params* is (name, annotation) or (name, annotation, default).
    """
    sig_params: list[Parameter] = []
    for p in params:
        name, annotation = p[0], p[1]
        default = p[2] if len(p) > 2 else Parameter.empty
        sig_params.append(Parameter(name, Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation, default=default))

    def handler(**kwargs):
        return fn(**kwargs)

    handler.__signature__ = Signature(sig_params)  # type: ignore[attr-defined]
    handler.__name__ = getattr(fn, "__name__", "handler")
    return handler


def _item_router(ep: dict, models: dict) -> APIRouter:
    model_name: str = ep["model"]
    id_param: str = ep.get("id_param", "item_id")

    ReadModel = models[model_name]
    CreateModel = models[f"{model_name}Create"]
    UpdateModel = models[f"{model_name}Update"]

    router = APIRouter(
        prefix=ep["prefix"],
        tags=[ep["tag"]],
        responses={404: {"description": "Not found"}},
    )

    def _create(**kw):
        return handle_item_creation(wikibase=kw["session"], model_obj=kw["body"], target_model=ReadModel)

    router.post("/", response_model=ReadModel, status_code=status.HTTP_201_CREATED)(
        _make_handler([("body", Annotated[CreateModel, Body()]), ("session", _AUTH)], _create)
    )

    def _get(**kw):
        return handle_get_item_by_id(wikibase=kw["session"], item_id=kw[id_param], target_model=ReadModel)

    router.get(f"/{{{id_param}}}", response_model=ReadModel, status_code=status.HTTP_200_OK)(
        _make_handler([(id_param, str), ("session", _AUTH)], _get)
    )

    def _update(**kw):
        return handle_item_update(
            wikibase=kw["session"],
            item_id=kw[id_param],
            model_obj=kw["body"],
            target_model=ReadModel,
        )

    router.put(f"/{{{id_param}}}", response_model=ReadModel, status_code=status.HTTP_200_OK)(
        _make_handler(
            [(id_param, _QID), ("body", Annotated[UpdateModel, Body()]), ("session", _AUTH)],
            _update,
        )
    )

    def _delete(**kw):
        return handle_item_deletion(
            wikibase=kw["session"],
            item_id=kw[id_param],
            reason=kw.get("reason"),
            target_model=ReadModel,
        )

    router.delete(f"/{{{id_param}}}", status_code=status.HTTP_204_NO_CONTENT)(
        _make_handler([(id_param, str), ("session", _AUTH), ("reason", _REASON, None)], _delete)
    )

    return router


def _statement_router(ep: dict, models: dict) -> APIRouter:
    model_name: str = ep["model"]
    parent_param: str = ep.get("parent_param", "item_id")
    has_delete_by_object: bool = ep.get("has_delete_by_object", False)
    has_get_by_id: bool = ep.get("has_get_by_id", False)

    ReadModel: Any = models[model_name]
    CreateModel = models[f"{model_name}Create"]
    UpdateModel = models[f"{model_name}Update"]
    BaseModel = models[f"{model_name}Base"]
    
    # Only enable delete_by_object if the model has the object_named_as field
    if has_delete_by_object:
        has_delete_by_object = "object_named_as" in BaseModel.model_fields

    router = APIRouter(
        prefix=ep["prefix"],
        tags=[ep["tag"]],
        responses={404: {"description": "Not found"}},
    )

    def _get_all(**kw):
        return handle_get_all_statements(wikibase=kw["session"], item_id=kw[parent_param], target_model=ReadModel)

    router.get("", response_model=list[ReadModel], status_code=status.HTTP_200_OK)(
        _make_handler([(parent_param, _QID), ("session", _AUTH)], _get_all)
    )

    def _create(**kw):
        return handle_statement_creation(
            wikibase=kw["session"],
            item_id=kw[parent_param],
            model_obj=kw["body"],
            target_model=ReadModel,
        )

    router.post("/", response_model=ReadModel, status_code=status.HTTP_200_OK)(
        _make_handler(
            [(parent_param, _QID), ("session", _AUTH), ("body", Annotated[CreateModel, Body()])],
            _create,
        )
    )

    if has_get_by_id:

        def _get_by_id(**kw):
            return handle_get_statement_by_id(
                wikibase=kw["session"],
                item_id=kw[parent_param],
                statement_id=kw["statement_id"],
                target_model=ReadModel,
            )

        router.get("/{statement_id}", response_model=ReadModel, status_code=status.HTTP_200_OK)(
            _make_handler([(parent_param, _QID), ("statement_id", str), ("session", _AUTH)], _get_by_id)
        )

    def _update(**kw):
        return handle_statement_update(
            wikibase=kw["session"],
            item_id=kw[parent_param],
            statement_id=kw["statement_id"],
            model_obj=kw["body"],
            target_model=ReadModel,
        )

    router.put("/{statement_id}", response_model=ReadModel, status_code=status.HTTP_200_OK)(
        _make_handler(
            [
                (parent_param, _QID),
                ("statement_id", str),
                ("body", Annotated[UpdateModel, Body()]),
                ("session", _AUTH),
            ],
            _update,
        )
    )

    def _delete_by_id(**kw):
        return handle_statement_deletion_by_id(
            wikibase=kw["session"],
            item_id=kw[parent_param],
            statement_id=kw["statement_id"],
            model=ReadModel,
        )

    router.delete("/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)(
        _make_handler([(parent_param, _QID), ("statement_id", str), ("session", _AUTH)], _delete_by_id)
    )

    if has_delete_by_object:

        def _delete_by_object(**kw):
            return handle_statement_deletion_by_object(
                wikibase=kw["session"],
                item_id=kw[parent_param],
                object_named_as=kw["object_named_as"],
                model=BaseModel,
            )

        router.delete("/", status_code=status.HTTP_204_NO_CONTENT)(
            _make_handler(
                [(parent_param, _QID), ("object_named_as", str), ("session", _AUTH)],
                _delete_by_object,
            )
        )

    return router


def generate_routers(schema_path: Path, models: dict) -> list[APIRouter]:
    """Derive the endpoint definitions from the schema classes and return a list of APIRouters."""
    routers: list[APIRouter] = []
    for ep in derive_endpoints(schema_path):
        if ep["type"] == "item":
            routers.append(_item_router(ep, models))
        elif ep["type"] == "statement":
            routers.append(_statement_router(ep, models))

    return routers
