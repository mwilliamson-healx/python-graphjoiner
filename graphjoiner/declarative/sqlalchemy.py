from __future__ import absolute_import

import graphql
import six
import sqlalchemy
from sqlalchemy.orm import Query

from graphjoiner import declarative
from . import field, ObjectType, relationship_builder


class SqlAlchemyObjectType(ObjectType):
    __abstract__ = True

    @classmethod
    def __primary_key__(cls):
        return cls.__model__.__mapper__.primary_key

    @classmethod
    def __select_all__(cls):
        return Query([]).select_from(cls.__model__)

    @classmethod
    def __fetch_immediates__(cls, selections, query, context):
        query = query.with_entities(*(
            selection.field.column
            for selection in selections
        ))
        for primary_key_column in cls.__primary_key__():
            query = query.add_columns(primary_key_column)

        return query.distinct().with_session(context.session).all()


def column_field(column, type=None):
    if type is None:
        type = _sql_type_to_graphql_type(column.type)
    return field(
        column=column,
        type=type,
    )


@relationship_builder
def select(local, target, join_query=None, join_fields=None):
    if join_fields is None:
        join_fields = {}
    else:
        join_fields = dict(
            (local_field.field_name, remote_field.field_name)
            for local_field, remote_field in six.iteritems(join_fields)
        )

    def generate_select(parent_select, context):
        target_select = target.__select_all__()
        if join_query is None:
            return target_select
        else:
            return join_query(parent_select, target_select)

    return generate_select, join_fields


@relationship_builder
def sql_value_join(local, target, join):
    def select(parent_select, context):
        return parent_select.with_entities(*(
                local_field.column.label(remote_field.attr_name)
                for local_field, remote_field in six.iteritems(join)
            )) \
            .with_session(context.session) \
            .all()

    join_fields = dict(
        (local_field.field_name, remote_field.field_name)
        for local_field, remote_field in six.iteritems(join)
    )

    return select, join_fields


@relationship_builder
def sql_join(local, target, join=None):
    if join is None:
        local_field_definition, remote_field_definition = _find_foreign_key(local, target)
        local_field = local_field_definition.field()
        remote_field = remote_field_definition.field()
        join = {local_field: remote_field}
    else:
        join = join.copy()

    def select(parent_select, context):
        parents = parent_select \
            .with_entities(*(
                local_field.column
                for local_field in join.keys()
            )) \
            .subquery()

        return target.__select_all__() \
            .join(parents, sqlalchemy.and_(
                parent_column == remote_field.column
                for parent_column, remote_field in zip(parents.c.values(), join.values())
            ))

    return select, dict(
        (local_field.field_name, remote_field.field_name)
        for local_field, remote_field in join.items()
    )


def _find_foreign_key(local, target):
    foreign_keys = list(_find_join_candidates(local, target))
    if len(foreign_keys) == 1:
        foreign_key, = foreign_keys
        return foreign_key
    else:
        raise Exception("TODO")

def _find_join_candidates(local, target):
    for local_field, target_field in _find_join_candidates_directional(local, target):
        yield local_field, target_field
    for target_field, local_field in _find_join_candidates_directional(target, local):
        yield local_field, target_field

def _find_join_candidates_directional(local, remote):
    for field_definition in _get_simple_field_definitions(local):
        orm_column = field_definition._kwargs["column"]
        if hasattr(orm_column, "property"):
            column, = orm_column.property.columns
            for foreign_key in column.foreign_keys:
                if remote.__model__.__table__ == foreign_key.column.table:
                    remote_primary_key_column, = foreign_key.column.table.primary_key
                    remote_field = _find_field_for_column(remote, remote_primary_key_column)
                    yield field_definition, remote_field


def _find_field_for_column(cls, column):
    for field_definition in _get_simple_field_definitions(cls):
        if field_definition._kwargs["column"] == column:
            return field_definition
    raise Exception("Could not find field in {} for {}".format(cls.__name__, column))

def _get_simple_field_definitions(cls):
    for field_definition in six.itervalues(cls.__dict__):
        if isinstance(field_definition, declarative.SimpleFieldDefinition):
            yield field_definition


_type_mappings = [
    (sqlalchemy.Integer, graphql.GraphQLInt),
    (sqlalchemy.Float, graphql.GraphQLFloat),
    (sqlalchemy.String, graphql.GraphQLString),
    (sqlalchemy.Boolean, graphql.GraphQLBoolean),
]

def _sql_type_to_graphql_type(sql_type):
    for mapped_sql_type, graphql_type in _type_mappings:
        if isinstance(sql_type, mapped_sql_type):
            return graphql_type

    raise Exception("Unknown SQL type: {}".format(sql_type))
