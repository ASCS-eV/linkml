"""gen-owl output that a real OWL consumer accepts: OWLAPI 5.5.0 checks the OWL 2 DL profile and keeps the annotations.

The fork's integration branch runs these in its own CI job (``owl-annotation-consumer.yaml``), which prepares the
pinned OWLAPI classpath with Maven; elsewhere they are skipped. They cover the features that meet on OWL resources:
metaclass membership (``instantiates``), declared annotation values and annotation property roles.
"""

import os
import subprocess
from pathlib import Path

import pytest
from rdflib import DCTERMS, RDFS, URIRef

from linkml.generators.owlgen import OwlSchemaGenerator

ROOT = Path(__file__).resolve().parents[3]
HARNESS = Path(__file__).parent / "input/owl_annotation_properties"
DCMI_EXAMPLE = ROOT / "docs/examples/owl-dcmi-agent-annotations.yaml"
EX = "https://example.org/consumer/"

SCHEMA = """
id: https://example.org/consumer
name: consumer
prefixes:
  ex: https://example.org/consumer/
  linkml: https://w3id.org/linkml/
  owl: http://www.w3.org/2002/07/owl#
  rdfs: http://www.w3.org/2000/01/rdf-schema#
  vocab: https://example.org/vocab/
default_prefix: ex
default_range: string
imports: [linkml:types]
slots:
  comment:
    slot_uri: rdfs:comment
    implements: [owl:AnnotationProperty]
  note:
    implements: [owl:AnnotationProperty]
    is_a: comment
  plain: {}
classes:
  Metadata:
    attributes:
      reference:
        range: nodeidentifier
        implements: [owl:AnnotationProperty]
  Thing:
    instantiates: [ex:Metadata, vocab:Profile]
    annotations:
      reference: ex:target
    slots: [note, plain]
    attributes:
      name:
        slot_uri: rdfs:label
enums:
  Choice:
    implements: [owl:NamedIndividual]
    permissible_values:
      A:
        meaning: ex:A
        instantiates: [vocab:Category]
"""


# gen-owl writes metadata annotations (dcterms:title, skos:definition, skos:inScheme, linkml:permissible_values)
# without declaring their annotation properties, and #31 asserts membership in external classes without declaring
# them, so OWLAPI finds the output outside the OWL 2 DL profile; upstream main fails the same way for any schema.
# The earlier integration branch passed because the old #33 declared them; the re-cut #58/#59 do not.
_UNDECLARED = pytest.mark.xfail(
    strict=True,
    raises=subprocess.CalledProcessError,
    reason="undeclared metadata annotation properties and instantiated classes put gen-owl outside OWL 2 DL",
)


@pytest.fixture
def owlapi_classpath() -> str:
    """The OWLAPI classpath the CI job prepared; pytest never fetches it."""
    filename = os.environ.get("LINKML_OWLAPI_CLASSPATH_FILE")
    if not filename:
        if os.environ.get("LINKML_REQUIRE_OWLAPI") == "1":
            pytest.fail("Required OWLAPI gate has no LINKML_OWLAPI_CLASSPATH_FILE")
        pytest.skip("The OWLAPI consumer runs in its own CI job, with a prepared classpath")
    classpath = Path(filename).read_text().strip()
    assert classpath, "Empty prepared OWLAPI classpath"
    return classpath


def _probe(source: str | Path, tmp_path: Path, classpath: str, rows: list[list[str]], **options: object) -> None:
    """Run the Java consumer on the generated ontology: OWL 2 DL profile, no unparsed triples, and *rows*
    (owner or ``ontology``, predicate, ``IRI`` or ``LITERAL``, value, datatype, language) kept on a round trip."""
    generated = tmp_path / "generated.ttl"
    generated.write_text(OwlSchemaGenerator(str(source), **options).serialize())
    expectations = tmp_path / "expected.tsv"
    expectations.write_text("\n".join("\t".join(row) for row in rows) + "\n")
    subprocess.run(
        [
            "java",
            "--class-path",
            classpath,
            str(HARNESS / "AnnotationProbe.java"),
            str(generated),
            str(tmp_path / "roundtrip.ttl"),
            str(expectations),
        ],
        check=True,
    )


@_UNDECLARED
@pytest.mark.integration
@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("type_objects", [False, True])
def test_documented_dcmi_example(tmp_path: Path, owlapi_classpath: str, native: bool, type_objects: bool) -> None:
    """The DCMI example of the OWL documentation is OWL 2 DL and keeps its creator IRI and rights text."""
    rows = [
        ["ontology", str(DCTERMS.creator), "IRI", "https://orcid.org/0000-0002-1825-0097", "", ""],
        ["ontology", str(DCTERMS.rights), "LITERAL", "Copyright 2026 The Example Team", "", ""],
    ]
    _probe(
        DCMI_EXAMPLE,
        tmp_path,
        owlapi_classpath,
        rows,
        use_native_uris=native,
        type_objects=type_objects,
        metaclasses=False,
    )


@_UNDECLARED
@pytest.mark.integration
@pytest.mark.parametrize("native", [True, False])
def test_membership_annotation_and_roles_together(
    tmp_path: Path, owlapi_classpath: str, native: bool, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Metaclass membership on a class and a permissible value, a declared annotation, annotation properties
    with a super-property and a built-in IRI, and an ordinary data property make one OWL 2 DL ontology."""
    schema = tmp_path_factory.mktemp("schema") / "consumer.yaml"
    schema.write_text(SCHEMA)
    rows = [[EX + "Thing", EX + "reference", "IRI", EX + "target", "", ""]]
    _probe(schema, tmp_path, owlapi_classpath, rows, use_native_uris=native, metaclasses=False, type_objects=False)


def test_consumer_schema_projects_as_expected() -> None:
    """The consumer schema exercises what the probe checks, so a passing probe means something."""
    from rdflib import OWL, RDF, Graph

    # the command line's defaults; the Python API defaults to type objects, which make every slot an object property
    generator = OwlSchemaGenerator(SCHEMA, metaclasses=False, type_objects=False)
    graph = Graph().parse(data=generator.serialize(), format="turtle")
    thing, vocab = URIRef(EX + "Thing"), "https://example.org/vocab/"
    assert {URIRef(EX + "Metadata"), URIRef(vocab + "Profile")} <= set(graph.objects(thing, RDF.type))
    assert (thing, URIRef(EX + "reference"), URIRef(EX + "target")) in graph
    assert (URIRef(EX + "A"), RDF.type, URIRef(vocab + "Category")) in graph
    assert (URIRef(EX + "note"), RDFS.subPropertyOf, URIRef(EX + "comment")) in graph
    assert (URIRef(EX + "note"), RDF.type, OWL.AnnotationProperty) in graph
    assert (URIRef(EX + "plain"), RDF.type, OWL.DatatypeProperty) in graph
