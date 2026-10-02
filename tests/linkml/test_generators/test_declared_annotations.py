"""Declared annotation ranges determine RDF terms independently of vocabulary."""

from pathlib import Path

import pytest
import yaml
from pyshacl import validate
from rdflib import RDF, SH, XSD, BNode, Graph, Literal, URIRef

from linkml.generators.owlgen import OwlSchemaGenerator
from linkml.generators.shaclgen import ShaclGenerator

EX = "https://example.org/"
SCHEMA = """
id: https://example.org/model
name: model
prefixes:
  ex: https://example.org/
  linkml: https://w3id.org/linkml/
imports: [linkml:types]
default_prefix: ex
types:
  Reference:
    typeof: nodeidentifier
  Text:
    typeof: string
classes:
  Metadata:
    class_uri: ex:Metadata
    attributes:
      reference:
        slot_uri: ex:reference
        range: Reference
      text:
        slot_uri: ex:text
        range: Text
  Profile:
    is_a: Metadata
    class_uri: ex:Profile
  Thing:
    instantiates: [ex:Profile]
    annotations:
      ex:reference: ex:target
      ex:text: https://example.org/literal-text
"""


def _graph(source: str | Path, generator: str, **kwargs: object) -> Graph:
    """Exercise generated Turtle, including term preservation after parsing."""
    if generator == "owl":
        output = OwlSchemaGenerator(source, **kwargs).serialize()
    else:
        output = ShaclGenerator(source, include_annotations=True, **kwargs).serialize()
    return Graph().parse(data=output, format="turtle")


@pytest.mark.parametrize("generator", ["owl", "shacl"])
@pytest.mark.parametrize("tag_form", ["local", "curie", "iri"])
@pytest.mark.parametrize("value", ["ex:target", "https://example.net/target", "urn:example:target"])
def test_declared_ranges(generator: str, tag_form: str, value: str) -> None:
    """Inherited declarations handle arbitrary predicates, CURIEs and absolute IRIs."""
    schema = yaml.safe_load(SCHEMA)
    prefix = {"local": "", "curie": "ex:", "iri": EX}[tag_form]
    schema["classes"]["Thing"]["annotations"] = {
        prefix + "reference": value,
        prefix + "text": EX + "literal-text",
    }
    graph = _graph(yaml.safe_dump(schema), generator)
    expected = URIRef(EX + "target" if value == "ex:target" else value)
    assert list(graph.objects(None, URIRef(EX + "reference"))) == [expected]
    assert list(graph.objects(None, URIRef(EX + "text"))) == [Literal(EX + "literal-text")]


@pytest.mark.parametrize("generator", ["owl", "shacl"])
@pytest.mark.parametrize("owner", ["class", "slot", "type"])
def test_metadata_owners(generator: str, owner: str) -> None:
    """Every annotated shape/resource uses the same declared term conversion."""
    schema = yaml.safe_load(SCHEMA)
    metadata = {"instantiates": ["ex:Profile"], "annotations": {"ex:reference": "ex:target"}}
    schema["classes"]["Thing"].pop("annotations")
    if owner == "class":
        schema["classes"]["Thing"].update(metadata)
    elif owner == "slot":
        schema["classes"]["Thing"]["attributes"] = {"value": {"range": "string", **metadata}}
    else:
        schema["types"]["Text"].update(metadata)
        schema["classes"]["Thing"]["attributes"] = {"value": {"range": "Text"}}
    graph = _graph(yaml.safe_dump(schema), generator)
    assert URIRef(EX + "target") in graph.objects(None, URIRef(EX + "reference"))


@pytest.mark.parametrize("generator", ["owl", "shacl"])
def test_imported_metaclass(tmp_path: Path, generator: str) -> None:
    """Imported definitions are resolved by class URI, including inherited slots."""
    profile = yaml.safe_load(SCHEMA)
    del profile["classes"]["Thing"]
    (tmp_path / "profile.yaml").write_text(yaml.safe_dump(profile))
    schema = yaml.safe_load(SCHEMA)
    schema["id"] = EX + "consumer"
    schema["imports"] = ["profile"]
    del schema["types"]
    schema["classes"] = {"Thing": schema["classes"]["Thing"]}
    source = tmp_path / "consumer.yaml"
    source.write_text(yaml.safe_dump(schema))
    assert URIRef(EX + "target") in _graph(source, generator).objects(None, URIRef(EX + "reference"))


@pytest.mark.parametrize("generator", ["owl", "shacl"])
@pytest.mark.parametrize("value", ["plain text", "relative/path", "https://example.org/%ZZ", 42])
def test_invalid_node_identifier_fails(generator: str, value: object) -> None:
    """A declared node cannot silently become a literal or an invalid RDF IRI."""
    schema = yaml.safe_load(SCHEMA)
    schema["classes"]["Thing"]["annotations"]["ex:reference"] = value
    with pytest.raises(ValueError, match="requires (an absolute IRI|a node identifier)"):
        _graph(yaml.safe_dump(schema), generator)


@pytest.mark.parametrize("generator", ["owl", "shacl"])
def test_blank_node_and_language(generator: str) -> None:
    """Explicit node identifiers allow blank nodes; only text receives a language tag."""
    schema = yaml.safe_load(SCHEMA)
    schema["classes"]["Thing"]["annotations"]["ex:reference"] = "_:target"
    graph = _graph(yaml.safe_dump(schema), generator, default_language="en")
    assert isinstance(next(graph.objects(None, URIRef(EX + "reference"))), BNode)
    assert Literal(EX + "literal-text", lang="en") in graph.objects(None, URIRef(EX + "text"))


@pytest.mark.parametrize("generator", ["owl", "shacl"])
def test_conflicting_metaclasses_fail(generator: str) -> None:
    """Different RDF terms cannot be selected by the order of metaclass declarations."""
    schema = yaml.safe_load(SCHEMA)
    schema["classes"]["Other"] = {"attributes": {"reference": {"slot_uri": "ex:reference", "range": "string"}}}
    schema["classes"]["Thing"]["instantiates"].append("ex:Other")
    with pytest.raises(ValueError, match="Conflicting metaclass"):
        _graph(yaml.safe_dump(schema), generator)


@pytest.mark.parametrize("generator", ["owl", "shacl"])
def test_uri_literal_is_distinct_from_node(generator: str) -> None:
    """The xsd:anyURI datatype does not by itself require an IRI node."""
    schema = yaml.safe_load(SCHEMA)
    schema["types"]["Text"]["uri"] = "xsd:anyURI"
    graph = _graph(yaml.safe_dump(schema), generator)
    assert Literal(EX + "literal-text", datatype=XSD.anyURI) in graph.objects(None, URIRef(EX + "text"))


@pytest.mark.parametrize("generator", ["owl", "shacl"])
def test_curie_range_requires_expansion(generator: str) -> None:
    """The standard curie type requires expansion in RDF despite its string datatype."""
    schema = yaml.safe_load(SCHEMA)
    schema["types"]["Reference"]["typeof"] = "curie"
    graph = _graph(yaml.safe_dump(schema), generator)
    assert URIRef(EX + "target") in graph.objects(None, URIRef(EX + "reference"))


@pytest.mark.parametrize("generator", ["owl", "shacl"])
@pytest.mark.parametrize("unsupported", ["structured", "class", "union"])
def test_unsupported_declared_representation_fails(generator: str, unsupported: str) -> None:
    """Unsupported values and mixed range expressions are not silently stringified."""
    schema = yaml.safe_load(SCHEMA)
    slot = schema["classes"]["Metadata"]["attributes"]["reference"]
    if unsupported == "structured":
        schema["classes"]["Thing"]["annotations"]["ex:reference"] = {"value": {"nested": "value"}}
    elif unsupported == "class":
        slot["range"] = "Thing"
    else:
        slot["any_of"] = [{"range": "nodeidentifier"}, {"range": "string"}]
    with pytest.raises(ValueError, match="scalar"):
        _graph(yaml.safe_dump(schema), generator)


def test_untyped_metadata_preserves_literal_values() -> None:
    """OWL does not infer RDF node kinds from familiar vocabulary names or URL text."""
    schema = yaml.safe_load(SCHEMA)
    schema["prefixes"]["dcterms"] = "http://purl.org/dc/terms/"
    schema["license"] = "https://example.org/license"
    schema["annotations"] = {"dcterms:license": "SPDX:MIT"}
    graph = _graph(yaml.safe_dump(schema), "owl")
    predicate = URIRef("http://purl.org/dc/terms/license")
    assert set(graph.objects(URIRef(EX + "model"), predicate)) == {
        Literal("https://example.org/license"),
        Literal("SPDX:MIT"),
    }


def test_owl_header_enum_and_permissible_value() -> None:
    """OWL annotation declarations also apply to the ontology and vocabulary resources."""
    schema = yaml.safe_load(SCHEMA)
    metadata = {"instantiates": ["ex:Profile"], "annotations": {"ex:reference": "ex:target"}}
    schema.update(metadata)
    schema["enums"] = {"Choice": {**metadata, "permissible_values": {"A": {"meaning": "ex:A", **metadata}}}}
    graph = _graph(yaml.safe_dump(schema), "owl")
    for subject in [EX + "model", EX + "Choice", EX + "A"]:
        assert (URIRef(subject), URIRef(EX + "reference"), URIRef(EX + "target")) in graph


def test_annotations_do_not_constrain_data() -> None:
    """Metadata appears on a shape without becoming a required data property."""
    graph = _graph(SCHEMA, "shacl")
    shape = next(graph.subjects(SH.targetClass, URIRef(EX + "Thing")))
    assert (shape, URIRef(EX + "reference"), URIRef(EX + "target")) in graph
    for prop in graph.objects(shape, SH.property):
        assert (prop, SH.path, URIRef(EX + "reference")) not in graph
    assert (shape, RDF.type, SH.NodeShape) in graph
    data = Graph()
    data.add((URIRef(EX + "instance"), RDF.type, URIRef(EX + "Thing")))
    assert validate(data, shacl_graph=graph, meta_shacl=True)[0]
