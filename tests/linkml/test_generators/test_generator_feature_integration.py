"""Consumer checks for features that overlap on the integration branch."""

import pytest
from pyshacl import validate
from rdflib import OWL, RDF, Graph, Namespace

from linkml.generators.owlgen import OwlSchemaGenerator
from linkml.generators.shaclgen import ShaclGenerator

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
    """A class keeps its metaclass membership (#31) next to its declared IRI-valued annotation (#58);
    a type keeps its membership, and gen-owl writes no annotations on types."""
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
