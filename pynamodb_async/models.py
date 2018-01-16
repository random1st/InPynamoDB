import copy
import inspect

from pynamodb.connection.base import MetaTable
from pynamodb.connection.util import pythonic
from pynamodb.exceptions import TableDoesNotExist
from pynamodb.models import Model as PynamoDBModel
from pynamodb_async.pagination import ResultIterator

from pynamodb_async.connection.table import TableConnection
from pynamodb_async.constants import PUT_FILTER_OPERATOR_MAP, READ_CAPACITY_UNITS, WRITE_CAPACITY_UNITS, \
    STREAM_VIEW_TYPE, STREAM_SPECIFICATION, STREAM_ENABLED, GLOBAL_SECONDARY_INDEXES, LOCAL_SECONDARY_INDEXES, \
    ATTR_DEFINITIONS, ATTR_NAME, QUERY_OPERATOR_MAP, QUERY_FILTER_OPERATOR_MAP


class InvalidUsageException(Exception):
    pass


class Model(PynamoDBModel):
    # TODO Check CRUD first
    def __init__(self, **attributes):
        if 'cls' not in inspect.stack()[1][0].f_locals or \
                inspect.stack()[1][0].f_locals['cls'].__class__.__name__ != 'MetaModel' or \
                inspect.stack()[1][3] != "create":
            raise InvalidUsageException("You should declare a model with create() factory method.")

        super().__init__(**attributes)

    @classmethod
    async def create(cls, hash_key=None, range_key=None, **attributes):
        if hash_key is not None:
            attributes[cls._dynamo_to_python_attr((await cls._get_meta_data()).hash_keyname)] = hash_key
        if range_key is not None:
            range_keyname = (await cls._get_meta_data()).range_keyname
            if range_keyname is None:
                raise ValueError(
                    "This table has no range key, but a range key value was provided: {0}".format(range_key)
                )
            attributes[cls._dynamo_to_python_attr(range_keyname)] = range_key

        return cls(**attributes)

    @classmethod
    async def create_table(cls, wait=False, read_capacity_units=None, write_capacity_units=None):
        """
        :param wait: argument for making this method identical to PynamoDB, but not-used variable
        :param read_capacity_units: Sets the read capacity units for this table
        :param write_capacity_units: Sets the write capacity units for this table
        """
        if not await cls.exists():
            schema = cls._get_schema()
            if hasattr(cls.Meta, pythonic(READ_CAPACITY_UNITS)):
                schema[pythonic(READ_CAPACITY_UNITS)] = cls.Meta.read_capacity_units
            if hasattr(cls.Meta, pythonic(WRITE_CAPACITY_UNITS)):
                schema[pythonic(WRITE_CAPACITY_UNITS)] = cls.Meta.write_capacity_units
            if hasattr(cls.Meta, pythonic(STREAM_VIEW_TYPE)):
                schema[pythonic(STREAM_SPECIFICATION)] = {
                    pythonic(STREAM_ENABLED): True,
                    pythonic(STREAM_VIEW_TYPE): cls.Meta.stream_view_type
                }
            if read_capacity_units is not None:
                schema[pythonic(READ_CAPACITY_UNITS)] = read_capacity_units
            if write_capacity_units is not None:
                schema[pythonic(WRITE_CAPACITY_UNITS)] = write_capacity_units
            index_data = cls._get_indexes()
            schema[pythonic(GLOBAL_SECONDARY_INDEXES)] = index_data.get(pythonic(GLOBAL_SECONDARY_INDEXES))
            schema[pythonic(LOCAL_SECONDARY_INDEXES)] = index_data.get(pythonic(LOCAL_SECONDARY_INDEXES))
            index_attrs = index_data.get(pythonic(ATTR_DEFINITIONS))
            attr_keys = [attr.get(pythonic(ATTR_NAME)) for attr in schema.get(pythonic(ATTR_DEFINITIONS))]
            for attr in index_attrs:
                attr_name = attr.get(pythonic(ATTR_NAME))
                if attr_name not in attr_keys:
                    schema[pythonic(ATTR_DEFINITIONS)].append(attr)
                    attr_keys.append(attr_name)
            result = await cls._get_connection().create_table(
                **schema
            )

            await cls._get_connection().connection.close_session()

            return result

    @classmethod
    async def from_raw_data(cls, data):
        """
        Returns an instance of this class
        from the raw data

        :param data: A serialized DynamoDB object
        """
        mutable_data = copy.copy(data)
        if mutable_data is None:
            raise ValueError("Received no mutable_data to construct object")
        meta_data = await cls._get_meta_data()
        hash_keyname = meta_data.hash_keyname
        range_keyname = meta_data.range_keyname
        hash_key_type = meta_data.get_attribute_type(hash_keyname)
        hash_key = mutable_data.pop(hash_keyname).get(hash_key_type)

        hash_key_attr = cls._get_attributes().get(cls._dynamo_to_python_attr(hash_keyname))

        hash_key = hash_key_attr.deserialize(hash_key)
        args = (hash_key,)
        kwargs = {}
        if range_keyname:
            range_key_attr = cls._get_attributes().get(cls._dynamo_to_python_attr(range_keyname))
            range_key_type = meta_data.get_attribute_type(range_keyname)
            range_key = mutable_data.pop(range_keyname).get(range_key_type)
            kwargs['range_key'] = range_key_attr.deserialize(range_key)
        for name, value in mutable_data.items():
            attr_name = cls._dynamo_to_python_attr(name)
            attr = cls._get_attributes().get(attr_name, None)
            if attr:
                kwargs[attr_name] = attr.deserialize(attr.get_value(value))
        return cls(*args, **kwargs)

    @classmethod
    async def query(cls,
                    hash_key,
                    range_key_condition=None,
                    filter_condition=None,
                    consistent_read=False,
                    index_name=None,
                    scan_index_forward=None,
                    conditional_operator=None,
                    limit=None,
                    last_evaluated_key=None,
                    attributes_to_get=None,
                    page_size=None,
                    **filters):
        """
        Provides a high level query API

        :param hash_key: The hash key to query
        :param range_key_condition: Condition for range key
        :param filter_condition: Condition used to restrict the query results
        :param consistent_read: If True, a consistent read is performed
        :param index_name: If set, then this index is used
        :param limit: Used to limit the number of results returned
        :param scan_index_forward: If set, then used to specify the same parameter to the DynamoDB API.
            Controls descending or ascending results
        :param conditional_operator:
        :param last_evaluated_key: If set, provides the starting point for query.
        :param attributes_to_get: If set, only returns these elements
        :param page_size: Page size of the query to DynamoDB
        :param filters: A dictionary of filters to be used in the query
        """
        cls._conditional_operator_check(conditional_operator)
        cls._get_indexes()
        if index_name:
            hash_key = cls._index_classes[index_name]._hash_key_attribute().serialize(hash_key)
            key_attribute_classes = cls._index_classes[index_name]._get_attributes()
            non_key_attribute_classes = cls._get_attributes()
        else:
            hash_key = (await cls._serialize_keys(hash_key))[0]
            non_key_attribute_classes = {}
            key_attribute_classes = {}
            for name, attr in cls._get_attributes().items():
                if attr.is_range_key or attr.is_hash_key:
                    key_attribute_classes[name] = attr
                else:
                    non_key_attribute_classes[name] = attr

        if page_size is None:
            page_size = limit

        key_conditions, query_filters = cls._build_filters(
            QUERY_OPERATOR_MAP,
            non_key_operator_map=QUERY_FILTER_OPERATOR_MAP,
            key_attribute_classes=key_attribute_classes,
            non_key_attribute_classes=non_key_attribute_classes,
            filters=filters)

        query_args = (hash_key,)
        query_kwargs = dict(
            range_key_condition=range_key_condition,
            filter_condition=filter_condition,
            index_name=index_name,
            exclusive_start_key=last_evaluated_key,
            consistent_read=consistent_read,
            scan_index_forward=scan_index_forward,
            limit=page_size,
            key_conditions=key_conditions,
            attributes_to_get=attributes_to_get,
            query_filters=query_filters,
            conditional_operator=conditional_operator
        )

        iterator = ResultIterator(
            cls._get_connection().query,
            query_args,
            query_kwargs,
            map_fn=cls.from_raw_data,
            limit=limit
        )

        await cls._get_connection().connection.close_session()

        return iterator

    @classmethod
    async def exists(cls):
        """
        Returns True if this table exists, False otherwise
        """
        try:
            await cls._get_connection().describe_table()
            return True
        except TableDoesNotExist:
            return False

    async def save(self, condition=None, conditional_operator=None, **expected_values):
        """
        Save this object to dynamodb
        """
        self._conditional_operator_check(conditional_operator)
        args, kwargs = self._get_save_args()
        if len(expected_values):
            kwargs.update(expected=self._build_expected_values(expected_values, PUT_FILTER_OPERATOR_MAP))
        kwargs.update(conditional_operator=conditional_operator)
        kwargs.update(condition=condition)

        result = await self._get_connection().put_item(*args, **kwargs)

        await self._get_connection().connection.close_session()

        return result

    @classmethod
    async def _range_key_attribute(cls):
        """
        Returns the attribute class for the hash key
        """
        attributes = cls._get_attributes()
        range_keyname = (await cls._get_meta_data()).range_keyname
        if range_keyname:
            attr = attributes[cls._dynamo_to_python_attr(range_keyname)]
        else:
            attr = None
        return attr

    @classmethod
    async def _hash_key_attribute(cls):
        """
        Returns the attribute class for the hash key
        """
        attributes = cls._get_attributes()
        hash_keyname = (await cls._get_meta_data()).hash_keyname
        return attributes[cls._dynamo_to_python_attr(hash_keyname)]

    @classmethod
    async def _get_meta_data(cls):
        """
        A helper object that contains meta data about this table
        """
        if cls._meta_table is None:
            cls._meta_table = MetaTable(await cls._get_connection().describe_table())
        return cls._meta_table

    @classmethod
    def _get_connection(cls):
        """
        Returns a (cached) connection
        """
        if not hasattr(cls, "Meta") or cls.Meta.table_name is None:
            raise AttributeError(
                """As of v1.0 PynamoDB Models require a `Meta` class.
                See https://pynamodb.readthedocs.io/en/latest/release_notes.html"""
            )
        if cls._connection is None:
            cls._connection = TableConnection(cls.Meta.table_name,
                                              region=cls.Meta.region,
                                              host=cls.Meta.host,
                                              session_cls=cls.Meta.session_cls,
                                              request_timeout_seconds=cls.Meta.request_timeout_seconds,
                                              max_retry_attempts=cls.Meta.max_retry_attempts,
                                              base_backoff_ms=cls.Meta.base_backoff_ms)
        return cls._connection

    @classmethod
    async def _serialize_keys(cls, hash_key, range_key=None):
        """
        Serializes the hash and range keys

        :param hash_key: The hash key value
        :param range_key: The range key value
        """
        hash_key = (await cls._hash_key_attribute()).serialize(hash_key)
        if range_key is not None:
            range_key = (await cls._range_key_attribute()).serialize(range_key)
        return hash_key, range_key