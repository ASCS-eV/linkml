"""``xsd:anyURI``: an IRI for ``uri`` and ``uriorcurie``, a typed literal for types derived from ``string``.

A schema can need both behaviours. A slot that points to a resource is an IRI node; a slot
that holds a URI reference as data - a relative file path such as ``./data/file.png`` - must
stay a literal, because JSON-LD resolves an ``@id`` against the document base and turns the
path into a machine-specific absolute IRI. The second is a type derived from ``string`` that
declares ``uri: xsd:anyURI``.

The OWL generator already decides by type ancestry (:func:`is_xsd_anyuri_range`). These tests
pin the JSON-LD context generator, the SHACL generator and the RDF dumper to the same rule.
"""

import json

import pytest
import yaml
from pyshacl import validate
from pyshex import ShExEvaluator
from rdflib import OWL, RDF, SH, XSD, BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic

from linkml.generators.jsonldcontextgen import ContextGenerator
from linkml.generators.owlgen import OwlSchemaGenerator
from linkml.generators.pythongen import PythonGenerator
from linkml.generators.shaclgen import ShaclGenerator
from linkml.generators.shexgen import ShExGenerator
from linkml_runtime.dumpers import rdflib_dumper
from linkml_runtime.utils.compile_python import compile_python
from linkml_runtime.utils.schemaview import SchemaView

SCHEMA = """
id: https://example.org/anyuri
name: anyuri
prefixes:
  ex: https://example.org/
  linkml: https://w3id.org/linkml/
imports:
  - linkml:types
default_prefix: ex
default_range: string

types:
  FilePath:
    typeof: string
    uri: xsd:anyURI
    description: A URI reference kept as a literal; it may be relative.
  Homepage:
    typeof: uri
    description: A uri by derivation, so an IRI.

slots:
  id:
    identifier: true
    range: uriorcurie
  link:
    range: uri
    slot_uri: ex:link
  homepage:
    range: Homepage
    slot_uri: ex:homepage
  path:
    range: FilePath
    slot_uri: ex:path

classes:
  Resource:
    slots: [id, link, homepage, path]
"""

EX = "https://example.org/"


@pytest.mark.parametrize("xsd_anyuri_as_iri", [False, True])
def test_context_keeps_string_derived_anyuri_a_literal(xsd_anyuri_as_iri: bool) -> None:
    """The existing option promotes only the URI family, not literal-valued types."""
    ctx = json.loads(ContextGenerator(SCHEMA, xsd_anyuri_as_iri=xsd_anyuri_as_iri).serialize())["@context"]
    assert ctx["path"]["@type"] == "xsd:anyURI"
    expected_iri = "@id" if xsd_anyuri_as_iri else "xsd:anyURI"
    assert ctx["link"]["@type"] == expected_iri
    assert ctx["homepage"]["@type"] == expected_iri


ANY_OF_SCHEMA = """
id: https://example.org/anyuri-any-of
name: anyuri_any_of
prefixes:
  ex: https://example.org/
  linkml: https://w3id.org/linkml/
imports:
  - linkml:types
default_prefix: ex
default_range: string
types:
  FilePath:
    typeof: string
    uri: xsd:anyURI
slots:
  either_path:
    slot_uri: ex:eitherPath
    any_of:
      - range: Target
      - range: FilePath
  either_uri:
    slot_uri: ex:eitherUri
    any_of:
      - range: Target
      - range: uri
classes:
  Target:
    class_uri: ex:Target
  Holder:
    slots: [either_path, either_uri]
"""


def test_context_any_of_with_string_derived_anyuri_is_not_promoted() -> None:
    """A mixed union coerces scalar values to literals; class values can use explicit node objects."""
    ctx = json.loads(ContextGenerator(ANY_OF_SCHEMA, xsd_anyuri_as_iri=True).serialize())["@context"]
    assert ctx["either_path"]["@type"] == "xsd:anyURI"
    # a uri branch agrees with the class branch, as before
    assert ctx["either_uri"]["@type"] == "@id"


def _property_shape(g: Graph, path: str) -> URIRef | BNode:
    """Find the generated property shape for an example property."""
    return next(ps for ps in g.subjects(SH.path, URIRef(EX + path)))


def test_shacl_string_derived_anyuri_is_a_typed_literal() -> None:
    """SHACL preserves literal types while retaining URI-family node kinds."""
    g = Graph().parse(data=ShaclGenerator(SCHEMA, mergeimports=True).serialize(), format="turtle")

    path = _property_shape(g, "path")
    assert g.value(path, SH.nodeKind) == SH.Literal
    assert g.value(path, SH.datatype) == XSD.anyURI

    for iri_slot in ("link", "homepage"):
        ps = _property_shape(g, iri_slot)
        assert g.value(ps, SH.nodeKind) == SH.IRI, iri_slot
        assert g.value(ps, SH.datatype) is None, iri_slot


@pytest.mark.parametrize("xsd_anyuri_as_iri", [False, True])
def test_owl_string_derived_anyuri_is_a_datatype_property(xsd_anyuri_as_iri: bool) -> None:
    """OWL and JSON-LD use the same option boundary."""
    g = OwlSchemaGenerator(SCHEMA, xsd_anyuri_as_iri=xsd_anyuri_as_iri, type_objects=False).as_graph()
    assert (URIRef(EX + "path"), RDF.type, OWL.DatatypeProperty) in g
    expected = OWL.ObjectProperty if xsd_anyuri_as_iri else OWL.DatatypeProperty
    assert (URIRef(EX + "link"), RDF.type, expected) in g


def test_dumper_string_derived_anyuri_is_a_typed_literal() -> None:
    """Generated Python instances preserve relative URI literals in RDF."""
    module = compile_python(str(PythonGenerator(SCHEMA, mergeimports=True).serialize()))
    resource = module.Resource(
        id="ex:r1",
        link="https://example.org/target",
        homepage="https://example.org/home",
        path="./data/file.png",
    )
    g = rdflib_dumper.as_rdf_graph(resource, schemaview=SchemaView(SCHEMA))
    subject = URIRef(EX + "r1")

    assert g.value(subject, URIRef(EX + "path")) == Literal("./data/file.png", datatype=XSD.anyURI)
    assert g.value(subject, URIRef(EX + "link")) == URIRef("https://example.org/target")
    assert g.value(subject, URIRef(EX + "homepage")) == URIRef("https://example.org/home")


@pytest.mark.parametrize("datatype", ["xsd:anyURI", "xs:anyURI", str(XSD.anyURI)])
@pytest.mark.parametrize("derived", [False, True])
@pytest.mark.parametrize("path", ["./data/file.png", "#section", "https://example.net/file"])
def test_rdf_representation_contract(datatype: str, derived: bool, path: str) -> None:
    """Generated contexts and Python RDF agree, and both shape languages validate them."""
    schema = yaml.safe_load(SCHEMA)
    schema["prefixes"]["xs"] = str(XSD)
    schema["types"]["FilePath"]["uri"] = datatype
    schema["types"]["Homepage"]["uri"] = datatype
    if derived:
        for name in ("FilePath", "Homepage"):
            schema["types"][name + "Child"] = {"typeof": name}
        schema["slots"]["path"]["range"] = "FilePathChild"
        schema["slots"]["homepage"]["range"] = "HomepageChild"
    source = yaml.safe_dump(schema)
    context = json.loads(ContextGenerator(source, xsd_anyuri_as_iri=True).serialize())["@context"]
    document = {
        "@context": context,
        "@type": "Resource",
        "id": "ex:r1",
        "link": "https://example.org/target",
        "homepage": "https://example.org/home",
        "path": path,
    }
    graph = Graph().parse(data=json.dumps(document), format="json-ld", publicID="https://unrelated.example/base/")
    subject = URIRef(EX + "r1")
    predicate = URIRef(EX + "path")
    assert graph.value(subject, predicate) == Literal(path, datatype=XSD.anyURI)
    module = compile_python(str(PythonGenerator(source).serialize()))
    instance = module.Resource(**{key: value for key, value in document.items() if not key.startswith("@")})
    dumped = rdflib_dumper.as_rdf_graph(instance, schemaview=SchemaView(source))
    assert isomorphic(graph, dumped)

    shacl = ShaclGenerator(source).as_graph()
    shex = ShExGenerator(source).serialize()
    assert validate(graph, shacl_graph=shacl, meta_shacl=True)[0]
    results = ShExEvaluator(rdf=graph, schema=shex, focus=subject, start=EX + "Resource").evaluate()
    assert results and all(result.result for result in results), [result.reason for result in results]
    owl = OwlSchemaGenerator(source, xsd_anyuri_as_iri=True, type_objects=False).as_graph()
    assert (predicate, RDF.type, OWL.DatatypeProperty) in owl
    assert (URIRef(EX + "homepage"), RDF.type, OWL.ObjectProperty) in owl

    for wrong in (URIRef("https://example.org/file"), Literal(path)):
        graph.set((subject, predicate, wrong))
        assert not validate(graph, shacl_graph=shacl)[0]
        results = ShExEvaluator(rdf=graph, schema=shex, focus=subject, start=EX + "Resource").evaluate()
        assert results and not any(result.result for result in results)


def test_context_uses_supplied_schema_without_reopening_source() -> None:
    """A source_file annotation is provenance, not permission to replace the given schema."""
    schema = SchemaView(SCHEMA).schema
    schema.source_file = "/not/a/real/schema.yaml"
    context = json.loads(ContextGenerator(schema, xsd_anyuri_as_iri=True).serialize())["@context"]
    assert context["path"]["@type"] == "xsd:anyURI"
    assert context["homepage"]["@type"] == "@id"


def test_uri_ancestry_with_string_datatype_is_not_promoted() -> None:
    """An explicit datatype override must agree across all generators."""
    schema = yaml.safe_load(SCHEMA)
    schema["types"]["Homepage"]["uri"] = "xsd:string"
    source = yaml.safe_dump(schema)
    context = json.loads(ContextGenerator(source, xsd_anyuri_as_iri=True).serialize())["@context"]
    assert context["homepage"].get("@type") != "@id"
    owl = OwlSchemaGenerator(source, xsd_anyuri_as_iri=True, type_objects=False).as_graph()
    assert (URIRef(EX + "homepage"), RDF.type, OWL.DatatypeProperty) in owl
    shacl = ShaclGenerator(source).as_graph()
    assert shacl.value(_property_shape(shacl, "homepage"), SH.datatype) == XSD.string
    dumper = rdflib_dumper.inject_triples("https://example.org/value", SchemaView(source), Graph(), "Homepage")
    assert dumper == Literal("https://example.org/value")


@pytest.mark.parametrize("as_node", [False, True])
def test_jsonld_union_preserves_literal_and_explicit_node_values(as_node: bool) -> None:
    """Both alternatives retain their RDF terms through JSON-LD expansion and SHACL."""
    context = json.loads(ContextGenerator(ANY_OF_SCHEMA, xsd_anyuri_as_iri=True).serialize())["@context"]
    value = {"@id": EX + "target", "@type": "Target"} if as_node else "./data/file.png"
    document = {"@context": context, "@id": EX + "holder", "@type": "Holder", "either_path": value}
    graph = Graph().parse(data=json.dumps(document), format="json-ld", publicID="https://unrelated.example/base/")
    expected = URIRef(EX + "target") if as_node else Literal(value, datatype=XSD.anyURI)
    assert graph.value(URIRef(EX + "holder"), URIRef(EX + "eitherPath")) == expected
    assert validate(graph, shacl_graph=ShaclGenerator(ANY_OF_SCHEMA).as_graph(), meta_shacl=True)[0]
    graph.set((URIRef(EX + "holder"), URIRef(EX + "eitherPath"), Literal("wrong datatype")))
    assert not validate(graph, shacl_graph=ShaclGenerator(ANY_OF_SCHEMA).as_graph())[0]
