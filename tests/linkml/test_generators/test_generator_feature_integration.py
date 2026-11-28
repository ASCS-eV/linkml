"""Consumer checks for features that overlap on the integration branch."""

import logging

import pytest
from pyshacl import validate
from rdflib import OWL, RDF, RDFS, SH, XSD, Graph, Literal, Namespace, URIRef

from linkml.generators.owlgen import OwlSchemaGenerator
from linkml.generators.shaclgen import ShaclGenerator
from linkml.utils.pattern_dialects import regex_for_xpath

EX = Namespace("https://example.org/integration/")


@pytest.mark.parametrize("diff_stable", [False, True])
@pytest.mark.parametrize(
    "value,details,expected",
    [
        ("ex:allowed", 'ex:allowed a ex:Resource ; ex:category "ok" .', True),
        ("ex:other", 'ex:other a ex:Resource ; ex:category "ok" .', False),
        ("ex:allowed", 'ex:allowed a ex:Resource ; ex:category "wrong" .', False),
        ("ex:allowed", "ex:allowed a ex:Resource .", False),
        ('"literal"', "", True),
        ('"other"', "", False),
    ],
)
def test_any_of_combines_pattern_and_range_expression(
    diff_stable: bool, value: str, details: str, expected: bool
) -> None:
    """Each branch enforces its pattern and nested constraints together after RDF serialization."""
    schema = """
id: https://example.org/integration
name: integration
prefixes:
  ex: https://example.org/integration/
  linkml: https://w3id.org/linkml/
default_prefix: ex
imports: [linkml:types]
classes:
  Thing:
    attributes:
      value:
        any_of:
          - range: Resource
            pattern: /allowed$
            range_expression:
              slot_conditions:
                category: {equals_string: ok, required: true}
          - range: string
            pattern: ^literal$
  Resource:
    attributes:
      category: {range: string}
"""
    shapes = ShaclGenerator(schema, closed=False, diff_stable=diff_stable).serialize()
    data = f"@prefix ex: <{EX}> . ex:thing a ex:Thing ; ex:value {value} . {details}"
    conforms, _, report = validate(
        data_graph=data,
        data_graph_format="turtle",
        shacl_graph=shapes,
        shacl_graph_format="turtle",
        meta_shacl=True,
    )
    assert conforms is expected, report


@pytest.mark.parametrize("diff_stable", [False, True])
def test_instantiates_and_declared_annotation_on_one_resource(diff_stable: bool) -> None:
    """A class keeps its metaclass membership (#31) next to its declared IRI-valued annotation
    (upstream linkml/linkml#4157, on ``main`` since 2026-11-04); a type keeps its membership,
    and gen-owl writes no annotations on types."""
    schema = """
id: https://example.org/integration
name: integration
prefixes:
  ex: https://example.org/integration/
  linkml: https://w3id.org/linkml/
  owl: http://www.w3.org/2002/07/owl#
default_prefix: ex
imports: [linkml:types]
classes:
  Metadata:
    class_uri: ex:Metadata
    attributes:
      reference:
        slot_uri: ex:reference
        range: nodeidentifier
        implements: [owl:AnnotationProperty]
  Annotated:
    class_uri: ex:Annotated
    instantiates: [ex:Metadata]
    annotations:
      reference: ex:target
types:
  Label:
    typeof: string
    instantiates: [ex:Metadata]
"""
    graph = Graph().parse(data=OwlSchemaGenerator(schema, diff_stable=diff_stable).serialize(), format="turtle")
    assert (EX.Annotated, RDF.type, EX.Metadata) in graph
    assert (EX.Annotated, EX.reference, EX.target) in graph
    assert (EX.reference, RDF.type, OWL.AnnotationProperty) in graph
    assert (EX.Label, RDF.type, EX.Metadata) in graph


# XPath regular expressions have neither "(?:" nor "{,n}" (XPath Functions 3.1 §5.6.1).
_PYTHON_PATTERN = r"^(?:ab)+x{,2}$"

_PATTERN_SCHEMA = f"""
id: https://example.org/integration
name: integration
prefixes:
  ex: https://example.org/integration/
  linkml: https://w3id.org/linkml/
default_prefix: ex
imports: [linkml:types]
types:
  Code:
    typeof: string
    pattern: "{_PYTHON_PATTERN}"
classes:
  Thing:
    attributes:
      plain: {{pattern: "{_PYTHON_PATTERN}"}}
      typed: {{range: Code}}
      branch:
        any_of:
          - {{range: string, pattern: "{_PYTHON_PATTERN}"}}
          - {{range: integer}}
      kind: {{range: string}}
      flag: {{range: string}}
      status: {{range: string}}
    any_of:
      - slot_conditions: {{kind: {{pattern: "{_PYTHON_PATTERN}"}}}}
      - slot_conditions: {{flag: {{required: true}}}}
    rules:
      - preconditions: {{slot_conditions: {{flag: {{pattern: "{_PYTHON_PATTERN}"}}}}}}
        postconditions: {{slot_conditions: {{status: {{required: true}}}}}}
"""


def test_every_pattern_in_shacl_is_written_for_xpath() -> None:
    """``sh:pattern`` and SPARQL's ``REGEX`` read XPath regular expressions, so every pattern gen-shacl
    writes is rewritten (``regex_for_xpath``, #71): of a slot, a type and an ``any_of`` branch (#30), and
    of a slot condition in a class expression (#29) and in a rule (#20)."""
    shapes = Graph().parse(data=ShaclGenerator(_PATTERN_SCHEMA, closed=False).serialize(), format="turtle")
    xpath = regex_for_xpath(_PYTHON_PATTERN)
    assert xpath == "^(ab)+x{0,2}$"
    assert set(shapes.objects(None, SH.pattern)) == {Literal(xpath)}
    # one sh:pattern each for the slot, the type, the branch and the class expression's condition
    assert len(list(shapes.subject_objects(SH.pattern))) == 4
    [query] = [str(q) for q in shapes.objects(None, SH.select)]
    assert f'REGEX( STR( ?pre0 ), "{xpath}" )' in query
    assert "(?:" not in query


@pytest.mark.parametrize(
    "properties,expected",
    [
        ('ex:kind "abab"', True),
        ('ex:kind "aba"', False),
        ('ex:flag "abx" ; ex:status "done"', True),
        ('ex:flag "abx"', False),
        ('ex:flag "other"', True),
    ],
)
def test_rewritten_patterns_keep_their_meaning(properties: str, expected: bool) -> None:
    """The class expression and the rule still accept and reject what the Python pattern does."""
    shapes = ShaclGenerator(_PATTERN_SCHEMA, closed=False).serialize()
    data = f"@prefix ex: <{EX}> . ex:thing a ex:Thing ; {properties} ."
    conforms, _, report = validate(
        data_graph=data, data_graph_format="turtle", shacl_graph=shapes, shacl_graph_format="turtle", meta_shacl=True
    )
    assert conforms is expected, report


_OWNER_NARROWING_SCHEMA = """
id: https://example.org/integration
name: integration
prefixes:
  ex: https://example.org/integration/
  linkml: https://w3id.org/linkml/
default_prefix: ex
default_range: string
imports: [linkml:types]
slots:
  s: {}
  t: {range: integer}
classes:
  D: {}
  Parent:
    slots: [s, t]
    slot_usage:
      s: {range: D}
  Child:
    is_a: Parent
    rules:
      - preconditions: {slot_conditions: {s: {required: true}}}
        postconditions: {slot_conditions: {t: {minimum_value: 1}}}
    any_of:
      - slot_conditions: {s: {required: true}}
      - slot_conditions: {t: {minimum_value: 2}}
"""


def test_conditions_read_in_their_owner_fit_the_kind_of_their_property(caplog) -> None:
    """A condition without a range of its own has the range of the slot it names in its owner (#70).
    Where the owner narrows a data property to a class, which no data property has, the rule and the
    any_of with such a condition are left out (#73), so no class fills a restriction on the data property."""
    with caplog.at_level(logging.WARNING, logger="linkml.generators.owlgen"):
        owl = OwlSchemaGenerator(_OWNER_NARROWING_SCHEMA, metaclasses=False, type_objects=False).serialize()
    graph = Graph().parse(data=owl, format="turtle")
    assert (EX.s, RDF.type, OWL.DatatypeProperty) in graph
    restrictions = set(graph.subjects(OWL.onProperty, EX.s))
    fillers = {graph.value(r, q) for r in restrictions for q in (OWL.allValuesFrom, OWL.someValuesFrom)} - {None}
    assert all(f == XSD.string or (f, RDF.type, RDFS.Datatype) in graph for f in fillers), fillers
    assert any(m.startswith("A rule of class 'Child' is not emitted") for m in caplog.messages)
    assert any(m.startswith("The any_of of class 'Child' is not emitted") for m in caplog.messages)


_STRINGS_ON_NODES_SCHEMA = """
id: https://example.org/integration
name: integration
prefixes:
  ex: https://example.org/integration/
  linkml: https://w3id.org/linkml/
default_prefix: ex
default_range: string
imports: [linkml:types]
enums:
  Color:
    permissible_values:
      red: {meaning: ex:Red}
      blue:
slots:
  color: {range: Color}
  media_type: {range: string, equals_string: application/ld+json}
classes:
  Item:
    slots: [color, media_type]
    slot_usage:
      color: {equals_string: red}
"""


@pytest.mark.parametrize("type_objects", [False, True])
def test_equals_string_stays_a_string_on_enums_and_types(type_objects: bool) -> None:
    """#71 gives a slot whose values are nodes no string constraints. Under #73 an enum that is a class,
    and a type under type_objects, have node values too, but their equals_string stays the string it is
    on main, not an IRI made from the string."""
    owl = OwlSchemaGenerator(_STRINGS_ON_NODES_SCHEMA, metaclasses=False, type_objects=type_objects).serialize()
    graph = Graph().parse(data=owl, format="turtle")
    assert not [t for t in graph.all_nodes() if isinstance(t, URIRef) and "://" not in t]
    assert {Literal("red"), Literal("application/ld+json")} <= set(graph.objects(None, RDF.first))
