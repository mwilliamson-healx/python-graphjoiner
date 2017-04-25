import attr
from graphql import GraphQLInt, GraphQLNonNull
from hamcrest import assert_that

from graphjoiner.declarative import executor, field, single, RootType, select, ObjectType
from ..matchers import is_successful_result


class StaticDataObjectType(ObjectType):
    __abstract__ = True

    @classmethod
    def __select_all__(cls):
        return cls.__records__

    @classmethod
    def __fetch_immediates__(cls, selections, records, context):
        return [
            tuple(
                getattr(record, selection.field.attr_name)
                for selection in selections
            )
            for record in records
        ]


def test_mutations_are_executed_serially():
    BoxRecord = attr.make_class("Box", ["value"])

    box = BoxRecord(0)

    class DictQuery(object):
        @staticmethod
        def __select_all__():
            return {}

        @staticmethod
        def __add_arg__(args, arg_name, arg_value):
            args[arg_name] = arg_value
            return args

    class Box(StaticDataObjectType):
        __records__ = [box]

        value = field(type=GraphQLInt)

    class BoxMutation(DictQuery, Box):
        @classmethod
        def __fetch_immediates__(cls, selections, query, context):
            box.value = query["value"]
            return Box.__fetch_immediates__(selections, [box], context)

    class MutationRoot(RootType):
        update_box = single(
            lambda: select(BoxMutation),
            args={"value": GraphQLNonNull(GraphQLInt)}
        )

    class Root(RootType):
        box = single(lambda: select(Box))

    result = executor(Root, mutation=MutationRoot)("""
        mutation {
            first: updateBox(value: 1) {
                value
            }
            second: updateBox(value: 3) {
                value
            }
            third: updateBox(value: 2) {
                value
            }
        }
    """)
    assert_that(result, is_successful_result(data={
        "first": {
            "value": 1,
        },
        "second": {
            "value": 3,
        },
        "third": {
            "value": 2,
        },
    }))