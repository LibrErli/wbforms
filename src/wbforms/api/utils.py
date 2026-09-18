import logging

from fastapi import HTTPException
from pydantic import BaseModel
from starlette import status
from wikibaseintegrator.entities import ItemEntity

from wbforms.datamodel.item import (
    EntityBase,
    ExtractedStatement,
    ItemBase,
    Statement,
    StatementBase,
)
from wbforms.wbgenerator import (
    StatementNotFoundError,
    add_statement_from_model,
    create_item_from_model,
    delete_property_statement_by_id,
    delete_statement_by_matching_model,
    get_item_statement_by_id,
    get_item_statement_by_model,
    get_model_from_item,
    get_models_from_qualified_statement,
    update_item_from_model,
    update_qualified_statement_from_model,
)
from wbforms.wikibase import Wikibase

logger = logging.getLogger(__name__)


def handle_get_item_by_id(wikibase: Wikibase, item_id: str, target_model: type[ItemBase]):
    """
    Get the item model by given id
    :param wikibase:
    :param item_id:
    :param target_model:
    :return:
    """
    try:
        item: ItemEntity = wikibase.get_item(item_id)
        model = get_model_from_item(item, target_model)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
    return model


def handle_item_deletion(
    wikibase: Wikibase,
    item_id: str,
    target_model: type[ItemBase],
    reason: str | None = None,
):
    """
    Handle item deletion
    :param wikibase:
    :param item_id:
    :param reason:
    :param target_model:
    :return:
    """
    try:
        logger.debug(f"Deleting item {item_id} of type {get_model_label(target_model)}")
        item = wikibase.get_item(item_id)
        wikibase.delete_entity(item, reason=reason)
    except Exception as e:
        logger.debug(f"Failed to delete item {item_id} of type {get_model_label(target_model)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def handle_item_update(
    wikibase: Wikibase,
    item_id: str,
    model_obj: EntityBase,
    target_model: type[ItemBase],
):
    """
    Handle item update
    :param wikibase:
    :param item_id:
    :param model_obj:
    :param target_model:
    :return:
    """
    try:
        logger.info(f"Updating item {item_id} ({model_obj})")
        item: ItemEntity = wikibase.get_item(item_id)
        update_item_from_model(model=model_obj, item=item)
        updated_item = wikibase.write_item(item, summary=f"Updates {get_model_label(target_model)} statements")
        updated_paper = get_model_from_item(updated_item, target_model)
        return updated_paper
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def handle_item_creation(wikibase: Wikibase, model_obj: EntityBase, target_model: type[ItemBase]):
    """
    Handle item creation
    :param wikibase:
    :param model_obj:
    :param target_model:
    :return:
    """
    try:
        item: ItemEntity = create_item_from_model(model_obj, wikibase.wbi)
        print(item.get_json())
        created_item = wikibase.write_item(item)
        created_model = get_model_from_item(created_item, target_model)
        return created_model
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def handle_statement_deletion_by_id(wikibase: Wikibase, item_id: str, statement_id: str, model: type[Statement]):
    """
    Handle statement deletion by id
    :param wikibase: wikibase instance to performe the action against
    :param item_id: Qid ot the item which has the statement
    :param statement_id: id of the statement
    :param model: model of the statement to delete
    :return: None if the deletion was successful
    :raise HTTPException if the statement was not found or some error occurred
    """
    try:
        item: ItemEntity = wikibase.get_item(item_id)
        is_removed = delete_property_statement_by_id(item, statement_id, model)
        if is_removed:
            wikibase.write_item(item, summary=f"Removes {get_model_label(model)}")
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Statement not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def handle_statement_deletion_by_object(
    wikibase: Wikibase,
    item_id: str,
    object_named_as: str,
    model: type[ExtractedStatement],
):
    """
    Handle statement deletion by object
    :param wikibase:
    :param item_id:
    :param object_named_as:
    :param model:
    :return:
    """
    try:
        item: ItemEntity = wikibase.get_item(item_id)
        # Only pass object_named_as if the model has this field
        kwargs = {"object_named_as": object_named_as} if "object_named_as" in model.model_fields else {}
        subject_to_delete = model(**kwargs)
        is_removed = delete_statement_by_matching_model(item, subject_to_delete)
        if is_removed:
            wikibase.write_item(item, summary=f"Removes {get_model_label(model)}")
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Statement not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def handle_statement_creation(
    wikibase: Wikibase,
    item_id: str,
    model_obj: StatementBase,
    target_model: type[Statement],
):
    """
    Handle statement creation
    :param wikibase:
    :param item_id:
    :param model_obj:
    :param target_model:
    :return:
    """
    try:
        item: ItemEntity = wikibase.get_item(item_id)
        add_statement_from_model(item, model_obj)
        updated_item = wikibase.write_item(item, summary=f"Adds {get_model_label(target_model)}")
        created_subject = get_item_statement_by_model(item=updated_item, model=model_obj, target_model=target_model)
        return created_subject
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def handle_statement_update(
    wikibase: Wikibase,
    item_id: str,
    statement_id: str,
    model_obj: StatementBase,
    target_model: type[Statement],
):
    """
    Handle statement update
    :param wikibase:
    :param item_id:
    :param statement_id:
    :param model_obj:
    :param target_model:
    :return:
    """
    try:
        logger.info(f"Updating statement {statement_id} ({model_obj})")
        item: ItemEntity = wikibase.get_item(item_id)
        try:
            update_qualified_statement_from_model(item=item, statement_id=statement_id, model=model_obj)
        except StatementNotFoundError:
            # The client-held statement id can be stale (e.g. a different/replicated revision was
            # read when the list was loaded). Re-resolve the target statement by its stable identity
            # (subject / object_named_as via the model __eq__) and retry once before giving up.
            existing = get_item_statement_by_model(item, model_obj, target_model)
            resolved_id = getattr(existing, "statement_id", None) if existing is not None else None
            if not resolved_id:
                raise
            logger.warning(f"statement_id {statement_id} stale; re-resolved to {resolved_id}")
            statement_id = resolved_id
            update_qualified_statement_from_model(item=item, statement_id=statement_id, model=model_obj)
        # Check if modification would invalidate the model → error is raised if invalid
        get_item_statement_by_id(item, statement_id, target_model)
        # modification is valid → push changes to wikibase
        updated_item = wikibase.write_item(item, summary=f"Update {get_model_label(target_model)}")
        updated_author_signature = get_item_statement_by_id(updated_item, statement_id, target_model)
        return updated_author_signature
    except HTTPException:
        raise
    except StatementNotFoundError as e:
        logger.warning(f"Statement update failed: item_id={item_id} statement_id={statement_id}: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def handle_get_all_statements(wikibase: Wikibase, item_id: str, target_model: type[Statement]) -> list[Statement]:
    """
    Get all statements of the given model
    :param wikibase:
    :param item_id:
    :param target_model:
    :return:
    """
    try:
        item: ItemEntity = wikibase.get_item(item_id)
        models = get_models_from_qualified_statement(item, target_model)
        return models
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def handle_get_statement_by_id(
    wikibase: Wikibase, item_id: str, statement_id: str, target_model: type[Statement]
) -> Statement:
    """
    Get statement by id
    :param wikibase:
    :param item_id:
    :param statement_id:
    :param target_model:
    :return:
    """
    try:
        item: ItemEntity = wikibase.get_item(item_id)
        model = get_item_statement_by_id(item, statement_id, target_model)
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Statement not found")
        else:
            return model
    except HTTPException:
        raise
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def get_model_label(model: type[BaseModel]) -> str:
    """
    Get the label of the given model
    :param model:
    :return:
    """
    if model.model_config and model.model_config.get("title") is not None:
        return model.model_config.get("title").lower()
    return camel_case_to_phrase(model.__name__).lower()


def camel_case_to_phrase(s: str) -> str:
    """
    converts the given camel case string to phrase string For Example 'CamelCase' to 'camel case'
    :param s:
    :return:
    """
    return "".join(" " + c if c.isupper() else c for c in s).strip()
