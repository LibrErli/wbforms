import functools
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from string import Template

from pydantic import BaseModel, HttpUrl
from SPARQLWrapper import JSON, POST, SPARQLWrapper
from wikibaseintegrator import WikibaseIntegrator, wbi_login
from wikibaseintegrator.entities import ItemEntity, PropertyEntity
from wikibaseintegrator.models import Snak

from wbforms.datamodel.auth import WikibaseAuthorizationConfig, WikibaseLoginTypes

logger = logging.getLogger(__name__)


def get_default_user_agent() -> str:
    """Get default user agent from settings or use fallback"""
    from wbforms.settings import get_settings
    settings = get_settings()
    if settings.request_header_user_agent:
        return settings.request_header_user_agent
    return f"wbforms/1.0 (Wikibase Forms Editor {date.today()})"


def log_execution_time(func):
    """
    Function decorator to log execution time of functions
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        logger.debug(f"Execution time of {func.__name__}: {execution_time:.4f} seconds")
        return result

    return wrapper


class Wikibase(BaseModel):
    """Wikibase server"""

    sparql_endpoint: HttpUrl
    website: HttpUrl
    item_prefix: HttpUrl
    property_prefix: HttpUrl
    mediawiki_api_url: HttpUrl
    mediawiki_rest_url: HttpUrl | None = None
    auth_config: WikibaseAuthorizationConfig | None = None

    @classmethod
    def chunks(cls, lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    @classmethod
    def execute_values_query_in_chunks(
        cls,
        query_template: Template,
        param_name: str,
        values: list[str],
        endpoint_url: HttpUrl,
        chunk_size: int = 1000,
    ):
        """Execute given query in chunks to speedup execution
        :param chunk_size:
        :param endpoint_url:
        :param query_template:
        :param param_name:
        :param values:
        :return:
        """
        lod = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for item_id_chunk in cls.chunks(values, chunk_size):
                source_items = "\n".join(item_id_chunk)
                query = query_template.substitute(**{param_name: source_items})
                logger.debug(f"Querying chunk of size {len(item_id_chunk)} labels from {endpoint_url}")
                future = executor.submit(
                    cls.execute_query,
                    query=query,
                    endpoint_url=endpoint_url,
                )
                futures.append(future)
            for future in as_completed(futures):
                lod_chunk = future.result()
                lod.extend(lod_chunk)
        return lod

    @classmethod
    def execute_query(cls, query: str, endpoint_url: HttpUrl) -> list[dict]:
        """Execute given query against given endpoint
        :param query:
        :param endpoint_url:
        :return:
        """
        if query is None:
            logger.debug("No query provided")
            return None
        query_first_line = query.split("\n")[0][:30] if query.strip().startswith("#") else ""
        query_hash = hashlib.sha512(query.encode("utf-8")).hexdigest()
        logger.debug(f"Executing SPARQL query {query_first_line} ({query_hash}) against {endpoint_url}")
        start = datetime.now()
        sparql = SPARQLWrapper(
            endpoint_url.unicode_string(),
            agent=get_default_user_agent(),
            returnFormat=JSON,
        )
        sparql.setQuery(query)
        sparql.setMethod(POST)
        resp = sparql.query().convert()
        lod_raw = resp.get("results", {}).get("bindings")
        logger.debug(
            f"Query ({query_hash}) execution finished! execution time : {(datetime.now() - start).total_seconds()}s, No. results: {len(lod_raw)}",  # noqa: E501
        )
        lod = []
        for d_raw in lod_raw:
            d = {key: record.get("value", None) for key, record in d_raw.items()}
            if d:
                lod.append(d)
        return lod

    @classmethod
    def execute_ask_query(cls, query: str, endpoint_url: HttpUrl) -> bool:
        """
        Execute given ask query against given endpoint
        :param query:
        :param endpoint_url:
        :return:
        """
        sparql = SPARQLWrapper(
            endpoint_url.unicode_string(),
            agent=get_default_user_agent(),
            returnFormat=JSON,
        )
        sparql.setQuery(query)
        sparql.setMethod(POST)
        resp = sparql.query().convert()
        return resp.get("boolean", False)

    def get_property_types_of(self, prop_ids: set[str]) -> dict[str, str]:
        """Get the property types for the given properties
        :param prop_ids:
        :return:
        """
        query_template = Template("""
        SELECT ?property ?type {
          VALUES ?property {
          $prop_ids
          }
          ?property rdf:type wikibase:Property.
          ?property wikibase:propertyType ?type.
        }
        """)
        values = []
        prefix = self.item_prefix.unicode_string()
        for prop_id in prop_ids:
            if not prop_id.startswith(prefix):
                prop_id = prefix + prop_id
            values.append(f"<{prop_id}>")

        lod = self.execute_values_query_in_chunks(
            query_template=query_template,
            param_name="prop_ids",
            values=values,
            endpoint_url=self.sparql_endpoint,
        )
        return {d.get("property"): d.get("type") for d in lod}

    def get_entity_label(
        self,
        entity_ids: list[str],
        language: str | None = None,
    ) -> dict[str, str]:
        """Get the labels for the given entities
        :param endpoint_url:
        :param entity_ids:
        :param language: if None english will be used
        :param item_prefix:
        :return:
        """
        query_raw = Template("""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?qid ?label
        WHERE{
          VALUES ?qid { 
            $entity_ids
          }
          ?qid rdfs:label ?label. FILTER(lang(?label)="$language")
        }
        """)
        if language is None:
            language = "de"
        query_template = Template(query_raw.safe_substitute(language=language, item_prefix=self.item_prefix))
        values = [f"<{entity_id}>" for entity_id in entity_ids]
        lod = self.execute_values_query_in_chunks(
            query_template=query_template,
            param_name="entity_ids",
            values=values,
            endpoint_url=self.sparql_endpoint,
        )
        return {d.get("qid"): d.get("label") for d in lod}

    def get_wbi_login(self) -> wbi_login._Login:
        """Get WikibaseIntegrator login
        :return:
        """
        # TODO: add mediawiki_rest_api to all logins
        if self.auth_config is None:
            return None
        match self.auth_config.auth_type:
            case WikibaseLoginTypes.OAUTH2:
                return wbi_login.OAuth2(
                    consumer_token=self.auth_config.consumer_token,
                    consumer_secret=self.auth_config.consumer_secret,
                    mediawiki_api_url=self.mediawiki_api_url.unicode_string(),
                )
            case WikibaseLoginTypes.OAUTH1:
                return wbi_login.OAuth1(
                    consumer_token=self.auth_config.consumer_token,
                    consumer_secret=self.auth_config.consumer_secret,
                    access_token=self.auth_config.access_token,
                    access_secret=self.auth_config.access_secret,
                    mediawiki_api_url=self.mediawiki_api_url.unicode_string(),
                )
            case WikibaseLoginTypes.BOT:
                return wbi_login.Login(
                    user=self.auth_config.user,
                    password=self.auth_config.password,
                    mediawiki_api_url=self.mediawiki_api_url.unicode_string(),
                    token_renew_period=60,
                )
            case WikibaseLoginTypes.USER:
                return wbi_login.Clientlogin(
                    user=self.auth_config.user,
                    password=self.auth_config.password,
                    mediawiki_api_url=self.mediawiki_api_url.unicode_string(),
                )
            case WikibaseLoginTypes.USER_OAUTH2:
                from wbforms.api.oauth_login import UserOAuth2

                if self.mediawiki_rest_url is None:
                    raise ValueError("mediawiki_rest_url must be configured for OAuth2 user login")
                return UserOAuth2(
                    access_token=self.auth_config.access_token,
                    refresh_token=self.auth_config.refresh_token,
                    client_id=self.auth_config.client_id,
                    client_secret=self.auth_config.client_secret,
                    mediawiki_api_url=self.mediawiki_api_url.unicode_string(),
                    mediawiki_rest_url=self.mediawiki_rest_url.unicode_string().rstrip("/"),
                )
            case _:
                return None

    @property
    @log_execution_time
    def wbi(self) -> WikibaseIntegrator:
        """Get wbi instance for this wikibase instance
        :return:
        """
        if not hasattr(self, "_wbi"):
            login = self.get_wbi_login()
            wbi = WikibaseIntegrator(login=login)
            self._wbi = wbi
        return self._wbi

    @log_execution_time
    def get_item(self, qid: str) -> ItemEntity:
        """Get wikibase item by id
        :param qid: Qid of the item
        :return:
        """
        qid = self.get_entity_id(qid)
        item = self.wbi.item.get(
            qid,
            mediawiki_api_url=self.mediawiki_api_url.unicode_string(),
            user_agent=get_default_user_agent(),
        )
        return item

    @log_execution_time
    def write_item(
        self,
        item: ItemEntity,
        summary: str | None = None,
        tags: list[str] | None = None,
        fix_known_issues: bool = False,
        max_retries: int | None = None,
    ) -> ItemEntity | None:
        """Write the given item to the wikibase instance
        :param max_retries:
        :param fix_known_issues:
        :param item: item to write
        :param summary: summary of the changes
        :param tags: tags to add to the edit
        :return:
        ToDo: add max retry for scheduled runs it needs to be low
        """
        kwargs = dict()
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        try:
            if fix_known_issues:
                self._fix_known_entity_issues(item)
            # Remove sitelinks to avoid validation errors when the linked pages don't exist
            # The editor doesn't modify sitelinks, so it's safe to remove them before writing
            if hasattr(item, 'sitelinks') and item.sitelinks:
                item.sitelinks.sitelinks.clear()
            res = item.write(
                mediawiki_api_url=self.mediawiki_api_url,
                summary=summary,
                tags=tags,
                login=self.wbi.login,
                user_agent=get_default_user_agent(),
                **kwargs,
            )
            return res
        except Exception as e:
            error_str = str(e)
            # If the error is about commonsMedia validation, remove those claims and retry
            if ("commonsmedia" in error_str.lower() or
                "does not exist on" in error_str.lower()):
                logger.warning(f"First write attempt failed due to validation: {e}. Removing commonsMedia claims and retrying...")
                # Remove commonsMedia claims
                claims_to_remove = []
                for claim in item.claims:
                    if claim.mainsnak and claim.mainsnak.datatype == "commonsMedia":
                        claims_to_remove.append(claim)
                for claim in claims_to_remove:
                    claim.remove()
                
                # Retry writing
                res = item.write(
                    mediawiki_api_url=self.mediawiki_api_url,
                    summary=summary,
                    tags=tags,
                    login=self.wbi.login,
                    user_agent=get_default_user_agent(),
                    **kwargs,
                )
                return res
            else:
                logger.error(f"Failed to write item {item.id}: {e}")
                raise e

    @staticmethod
    def get_entity_id(entity_url: str) -> str:
        """Get the ID of the given entity url without the namespace prefix
        :param entity_url:
        :return:
        """
        return entity_url.split("/")[-1]

    def get_items_modified_at(self, start_date: datetime | date, end_date: datetime | date | None = None) -> set[str]:
        """Get items modified at a date range
        :param start_date:
        :param end_date:
        :return:
        """
        query_template = Template("""
        PREFIX schema: <http://schema.org/>
        SELECT DISTINCT ?item
        WHERE {
          ?item schema:dateModified ?dateModified.
          FILTER ( ?dateModified >= "$start_date"^^xsd:dateTime && ?dateModified <= "$end_date"^^xsd:dateTime)
        }
        """)
        if end_date is None:
            end_date = start_date + timedelta(days=1)
        query = query_template.substitute(start_date=start_date.isoformat(), end_date=end_date.isoformat())
        lod = self.execute_query(query, self.sparql_endpoint)
        return {d.get("item", "") for d in lod if isinstance(d.get("item"), str)}

    def _fix_known_entity_issues(self, entity: ItemEntity | PropertyEntity):
        """Fix known issues with entities that lead to a denial of the mediawiki api
        Errors that are fixed
        - coordinate precision not set
        :param entity:
        :return:
        """
        for claim in entity.claims:
            self._fix_snak(claim.mainsnak)
            for qualifier in claim.qualifiers:
                self._fix_snak(qualifier)
            for reference in claim.references:
                for snak in reference.snaks:
                    self._fix_snak(snak)

    def _fix_snak(self, snak: Snak):
        """Fix known issues of snaks
        :param snak:
        :return:
        """
        if snak.datatype == "globe-coordinate" and snak.datavalue.get("value", {}).get("precision") is None:
            # https://github.com/wikimedia/Wikibase/blob/174450de8fdeabcf97287604dbbf04d07bb5000c/repo/includes/Rdf/Values/GlobeCoordinateRdfBuilder.php#L120
            snak.datavalue["value"]["precision"] = 1 / 3600

    def normalize_entity_id(self, entity_id: str) -> str:
        """Normalize entity id to a url
        :param entity_id: id to normalize
        :return:
        """
        if entity_id.startswith(self.item_prefix.unicode_string()):
            return entity_id
        return f"{self.item_prefix.unicode_string()}:{entity_id}"

    def delete_entity(self, entity: ItemEntity, reason: str | None = None, **kwargs):
        """
        Delete the given entity
        :param entity:
        :return:
        """
        entity.delete(
            mediawiki_api_url=self.mediawiki_api_url,
            reason=reason,
            login=self.wbi.login,
            user_agent=get_default_user_agent(),
            **kwargs,
        )
