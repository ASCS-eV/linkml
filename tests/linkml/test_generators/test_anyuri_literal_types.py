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
from rdflib import OWL, RDF, SH, XSD, Graph, Literal, URIRef

from linkml.generators.jsonldcontextgen import ContextGenerator
from linkml.generators.owlgen import OwlSchemaGenerator
from linkml.generators.pythongen import PythonGenerator
from linkml.generators.shaclgen import ShaclGenerator
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
def test_context_keeps_string_derived_anyuri_a_literal(xsd_anyuri_as_iri):
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


def test_context_any_of_with_string_derived_anyuri_is_not_promoted():
    """A class branch is @id; a literal-type branch is not, so the branches disagree and nothing is coerced."""
    ctx = json.loads(ContextGenerator(ANY_OF_SCHEMA, xsd_anyuri_as_iri=True).serialize())["@context"]
    assert ctx.get("either_path", {}).get("@type") != "@id"
    # a uri branch agrees with the class branch, as before
    assert ctx["either_uri"]["@type"] == "@id"


def _property_shape(g, path):
    return next(ps for ps in g.subjects(SH.path, URIRef(EX + path)))


def test_shacl_string_derived_anyuri_is_a_typed_literal():
    g = Graph().parse(data=ShaclGenerator(SCHEMA, mergeimports=True).serialize(), format="turtle")

    path = _property_shape(g, "path")
    assert g.value(path, SH.nodeKind) == SH.Literal
    assert g.value(path, SH.datatype) == XSD.anyURI

    for iri_slot in ("link", "homepage"):
        ps = _property_shape(g, iri_slot)
        assert g.value(ps, SH.nodeKind) == SH.IRI, iri_slot
        assert g.value(ps, SH.datatype) is None, iri_slot


@pytest.mark.parametrize("xsd_anyuri_as_iri", [False, True])
def test_owl_string_derived_anyuri_is_a_datatype_property(xsd_anyuri_as_iri):
    g = OwlSchemaGenerator(SCHEMA, xsd_anyuri_as_iri=xsd_anyuri_as_iri, type_objects=False).as_graph()
    assert (URIRef(EX + "path"), RDF.type, OWL.DatatypeProperty) in g
    expected = OWL.ObjectProperty if xsd_anyuri_as_iri else OWL.DatatypeProperty
    assert (URIRef(EX + "link"), RDF.type, expected) in g


def test_dumper_string_derived_anyuri_is_a_typed_literal():
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
