import re

from graphql import GraphQLArgument
import six

import graphjoiner


def executor(root):
    root_type = root._graphjoiner
    
    def execute(*args, **kwargs):
        return graphjoiner.execute(root_type, *args, **kwargs)
    
    return execute


def root_type(cls):
    return create_join_type(cls, joiner=RootJoiner())


class RootJoiner(object):
    def fetch_immediates(self, *args):
        return [{}]
    
    def relationship(self, target, join):
        def select(parent_select, context):
            return target._joiner.select_all()
        
        return select, {}


def object_type(cls):
    return create_join_type(cls, joiner=ObjectJoiner(cls))


class ObjectJoiner(object):
    def __init__(self, owner):
        self._owner = owner
    
    def fetch_immediates(self, selections, query, context):
        return self._owner.__fetch_immediates__(selections, query, context)
    
    def simple_field(self, **kwargs):
        return graphjoiner.field(**kwargs)


def create_join_type(cls, joiner):
    def fields():
        return dict(
            (field_definition.field_name, field_definition.__get__(None, cls))
            for key, field_definition in six.iteritems(cls.__dict__)
            if isinstance(field_definition, FieldDefinition)
        )
    
    cls._graphjoiner = graphjoiner.JoinType(
        name=cls.__name__,
        fields=fields,
        fetch_immediates=joiner.fetch_immediates,
    )
    cls._joiner = joiner
    
    for key, field_definition in six.iteritems(cls.__dict__):
        if isinstance(field_definition, FieldDefinition):
            field_definition.attr_name = key
            field_definition.field_name = _snake_case_to_camel_case(key)
            field_definition._owner = cls
    
    return cls


class FieldDefinition(object):
    _owner = None
    _value = None
    
    def __get__(self, obj, type=None):
        if self._owner is None:
            self._owner = type
            
        return self.field()
    
    def field(self):
        if self._value is None:
            self._value = self.instantiate()
            self._value.field_name = self.field_name
            self._value.attr_name = self.attr_name
        
        return self._value


def field(**kwargs):
    return SimpleFieldDefinition(**kwargs)


class SimpleFieldDefinition(FieldDefinition):
    def __init__(self, **kwargs):
        self._kwargs = kwargs
    
    def instantiate(self):
        return self._owner._joiner.simple_field(**self._kwargs)


def single(target, join=None):
    return RelationshipDefinition(graphjoiner.single, target, join)


def many(target, join=None):
    return RelationshipDefinition(graphjoiner.many, target, join)


class RelationshipDefinition(FieldDefinition):
    def __init__(self, func, target, join):
        self._func = func
        self._target = target
        self._join = join
        self._args = []
    
    def instantiate(self):
        generate_select, join = self._owner._joiner.relationship(self._target, self._join)
        
        def generate_select_with_args(args, parent_select, context):
            select = generate_select(parent_select, context)
        
            for arg_name, _, refine_select in self._args:
                if arg_name in args:
                    select = refine_select(select, args[arg_name])
            
            return select
        
        args = dict(
            (arg_name, GraphQLArgument(arg_type))
            for arg_name, arg_type, _ in self._args
        )
            
        # TODO: in general join selection needs to consider both sides of the relationship
        return self._func(self._target._graphjoiner, generate_select_with_args, join=join, args=args)
        
    def arg(self, arg_name, arg_type):
        def add_arg(refine_select):
            self._args.append((arg_name, arg_type, refine_select))
        
        return add_arg
    

def extract(relationship, field_name):
    return ExtractFieldDefinition(relationship, field_name)


class ExtractFieldDefinition(FieldDefinition):
    def __init__(self, relationship, field_name):
        self._relationship = relationship
        self._field_name = field_name
    
    def instantiate(self):
        return graphjoiner.extract(self._relationship.field(), self._field_name)


def lazy_field(func):
    return LazyFieldDefinition(func=func)
        
        
class LazyFieldDefinition(FieldDefinition):
    def __init__(self, func):
        self._func = func
        self._value = None
    
    def instantiate(self):
        field_definition = self._func()
        field_definition.field_name = self.field_name
        field_definition.attr_name = self.attr_name
        return field_definition.__get__(None, self._owner)


def _snake_case_to_camel_case(value):
    return value[0].lower() + re.sub(r"_(.)", lambda match: match.group(1).upper(), value[1:])
