"""Explicit OWL roles, real consumers, and the executed generic documentation example."""

import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
import yaml
from click.testing import CliRunner
from jsonasobj2 import as_dict
from pyshacl import validate
from pyshex import ShExEvaluator
from rdflib import DCTERMS, OWL, RDF, RDFS, SH, SKOS, XSD, Graph, Literal, URIRef

from linkml.generators.jsonldcontextgen import ContextGenerator
from linkml.generators.jsonldgen import JSONLDGenerator
from linkml.generators.jsonschemagen import JsonSchemaGenerator
from linkml.generators.owlgen import MetadataProfile, OwlSchemaGenerator, cli
from linkml.generators.pythongen import PythonGenerator
from linkml.generators.rdfgen import RDFGenerator
from linkml.generators.shaclgen import ShaclGenerator
from linkml.generators.shexgen import ShExGenerator
from linkml_runtime import SchemaView
from linkml_runtime.dumpers import json_dumper
from linkml_runtime.loaders import yaml_loader

EX = "https://example.org/"
ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "docs/examples/owl-annotation-properties.yaml"
HARNESS = Path(__file__).parent / "input/owl_annotation_properties"


@pytest.fixture
def schema() -> dict:
    """Load the same source that Sphinx includes in the OWL documentation."""
    return yaml.safe_load(EXAMPLE.read_text())


def _generator(schema: dict, **options: object) -> OwlSchemaGenerator:
    """Use explicit CLI-like options so profile claims have a precise boundary."""
    return OwlSchemaGenerator(
        yaml.safe_dump(schema),
        **{"use_native_uris": False, "metaclasses": False, "type_objects": False, **options},
    )


def _graph(schema: dict, **options: object) -> Graph:
    """Parse the direct serialized artifact without any graph repair."""
    return Graph().parse(data=_generator(schema, **options).serialize(), format="turtle")


def _assert_annotation_roles(graph: Graph) -> None:
    """APs must not occur in logical restrictions, keys, inverses or characteristics."""
    for predicate in graph.subjects(RDF.type, OWL.AnnotationProperty):
        assert (predicate, RDF.type, OWL.ObjectProperty) not in graph
        assert (predicate, RDF.type, OWL.DatatypeProperty) not in graph
        assert not list(graph.subjects(OWL.onProperty, predicate))
        assert not list(graph.triples((predicate, OWL.inverseOf, None)))
        assert not list(graph.triples((None, OWL.inverseOf, predicate)))
        for key in graph.objects(None, OWL.hasKey):
            assert predicate not in graph.items(key)
        for characteristic in [OWL.SymmetricProperty, OWL.TransitiveProperty, OWL.FunctionalProperty]:
            assert (predicate, RDF.type, characteristic) not in graph


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("type_objects", [False, True])
def test_documented_annotation_projection(schema: dict, native: bool, type_objects: bool) -> None:
    """RDF value kind and property role remain independent under both URI/type modes."""
    graph = _graph(schema, use_native_uris=native, type_objects=type_objects)
    assert (URIRef(EX + "model"), URIRef(EX + "reference"), URIRef(EX + "target")) in graph
    assert (URIRef(EX + "model"), URIRef(EX + "text"), Literal(EX + "a-textual-label")) in graph
    for name in ["reference", "text"]:
        assert (URIRef(EX + name), RDF.type, OWL.AnnotationProperty) in graph
    assert (SKOS.inScheme, RDF.type, OWL.AnnotationProperty) in graph
    _assert_annotation_roles(graph)


@pytest.mark.parametrize(
    "role", ["owl:AnnotationProperty", "alternate:AnnotationProperty", str(OWL.AnnotationProperty)]
)
def test_expanded_role_and_unrelated_implements(schema: dict, role: str) -> None:
    """Equivalent CURIEs/full IRIs resolve identically and unrelated mappings are retained."""
    schema["prefixes"]["alternate"] = str(OWL)
    schema["classes"]["OntologyMetadata"]["attributes"]["reference"]["implements"] = ["ex:Interface", role]
    graph = _graph(schema)
    assert (URIRef(EX + "reference"), RDF.type, OWL.AnnotationProperty) in graph
    _assert_annotation_roles(graph)


@pytest.mark.parametrize("role", ["owl:ObjectProperty", "owl:DatatypeProperty"])
def test_conflicting_explicit_roles(schema: dict, role: str) -> None:
    """The order of implements entries cannot choose among incompatible roles."""
    schema["classes"]["OntologyMetadata"]["attributes"]["reference"]["implements"].append(role)
    with pytest.raises(ValueError, match="Conflicting OWL property roles.*reference"):
        _graph(schema)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("role", ["owl:ObjectProperty", "owl:DatatypeProperty"])
def test_metadata_data_collision(schema: dict, native: bool, role: str) -> None:
    """Shared output IRIs cannot have both AP and data-property roles."""
    schema["classes"]["Data"] = {
        "attributes": {"reference": {"slot_uri": "ex:reference", "range": "string", "implements": [role]}}
    }
    with pytest.raises(ValueError, match="Conflicting OWL property roles.*https://example.org/reference"):
        _graph(schema, use_native_uris=native)


def test_mapped_and_local_predicates_are_distinct(schema: dict) -> None:
    """Native property URIs need not equal the mapped annotation URI."""
    schema["classes"]["Data"] = {"attributes": {"value": {"slot_uri": "ex:reference", "range": "string"}}}
    _assert_annotation_roles(_graph(schema, use_native_uris=True))
    with pytest.raises(ValueError, match="Conflicting OWL property roles.*reference"):
        _graph(schema, use_native_uris=False)


def test_missing_ap_role_is_not_inferred_from_instantiates(schema: dict) -> None:
    """Instantiation and a node range do not convert ordinary properties to APs."""
    for slot in schema["classes"]["OntologyMetadata"]["attributes"].values():
        del slot["implements"]
    with pytest.raises(ValueError, match="Conflicting OWL property roles.*reference"):
        _graph(schema)


@pytest.mark.parametrize("role", ["owl:ObjectProperty", "owl:DatatypeProperty"])
def test_undeclared_annotations_preserve_logical_rdf_projection(schema: dict, role: str) -> None:
    """Untyped metadata on a known logical predicate retains its existing role, terms and restrictions."""
    schema["classes"]["Data"] = {
        "attributes": {"value": {"range": "string", "implements": [role]}},
        "annotations": {"ex:value": "https://example.org/intentional-text"},
    }
    graph = _graph(schema)
    predicate = URIRef(EX + "value")
    assert (URIRef(EX + "Data"), predicate, Literal(EX + "intentional-text")) in graph
    assert (predicate, RDF.type, URIRef(str(OWL) + role.split(":")[1])) in graph
    assert (predicate, RDF.type, OWL.AnnotationProperty) not in graph
    assert list(graph.subjects(OWL.onProperty, predicate))


def test_native_metadata_preserves_known_logical_role(schema: dict) -> None:
    """Native metadata preserves a schema's logical mapping and its original RDF terms."""
    schema["prefixes"]["skos"] = str(SKOS)
    schema["classes"]["Data"] = {}
    schema["slots"] = {"origin": {"slot_uri": "skos:inScheme", "range": "string"}}
    graph = _graph(schema)
    assert (URIRef(EX + "Data"), SKOS.inScheme, URIRef(EX + "model")) in graph
    assert (SKOS.inScheme, RDF.type, OWL.DatatypeProperty) in graph
    assert (SKOS.inScheme, RDF.type, OWL.AnnotationProperty) not in graph
    assert (SKOS.inScheme, RDFS.range, XSD.string) in graph


@pytest.mark.parametrize("mergeimports", [False, True])
@pytest.mark.parametrize("expression_only", [False, True])
def test_imported_role_conflict(schema: dict, tmp_path: Path, mergeimports: bool, expression_only: bool) -> None:
    """An available imported definition participates even without merged output."""
    imported = deepcopy(schema)
    imported["id"] = EX + "imported"
    imported.pop("annotations")
    imported.pop("instantiates")
    definition = {"any_of": [{"range": "string"}, {"range": "integer"}]} if expression_only else {"range": "string"}
    imported["classes"] = {"Data": {"attributes": {"reference": definition}}}
    (tmp_path / "imported.yaml").write_text(yaml.safe_dump(imported))
    schema["imports"].append("imported")
    source = tmp_path / "model.yaml"
    source.write_text(yaml.safe_dump(schema))
    with pytest.raises(ValueError, match="Conflicting OWL property roles.*reference"):
        OwlSchemaGenerator(source, mergeimports=mergeimports, metaclasses=False, type_objects=False).serialize()


@pytest.mark.parametrize("mergeimports", [False, True])
def test_imported_inherited_mixin_roles(schema: dict, tmp_path: Path, mergeimports: bool) -> None:
    """Inherited and mixed-in AP definitions remain available to metadata resolution."""
    profile = deepcopy(schema)
    profile.pop("instantiates")
    profile.pop("annotations")
    profile["id"] = EX + "profile"
    profile["classes"]["OntologyMetadata"]["mixin"] = True
    (tmp_path / "profile.yaml").write_text(yaml.safe_dump(profile))
    schema["imports"].append("profile")
    schema["classes"] = {"Profile": {"mixins": ["OntologyMetadata"]}}
    schema["instantiates"] = ["ex:Profile"]
    source = tmp_path / "model.yaml"
    source.write_text(yaml.safe_dump(schema))
    graph = Graph().parse(data=OwlSchemaGenerator(source, mergeimports=mergeimports).serialize(), format="turtle")
    assert (URIRef(EX + "model"), URIRef(EX + "reference"), URIRef(EX + "target")) in graph
    _assert_annotation_roles(graph)


def test_slot_usage_and_inheritance(schema: dict) -> None:
    """Inherited implements survives slot_usage induction without mutating the view."""
    attributes = schema["classes"]["OntologyMetadata"].pop("attributes")
    schema["slots"] = attributes
    schema["classes"]["OntologyMetadata"]["slots"] = list(attributes)
    schema["classes"]["Child"] = {"is_a": "OntologyMetadata", "slot_usage": {"reference": {"required": True}}}
    generator = _generator(schema)
    before = as_dict(generator.schemaview.schema)
    first = generator.serialize()
    assert as_dict(generator.schemaview.schema) == before
    assert generator.serialize() == first
    _assert_annotation_roles(Graph().parse(data=first, format="turtle"))


@pytest.mark.parametrize(
    "field",
    [
        "inverse",
        "symmetric",
        "asymmetric",
        "transitive",
        "reflexive",
        "irreflexive",
        "designates_type",
        "has_member",
        "all_members",
    ],
)
def test_explicit_logical_annotation_use_fails(schema: dict, field: str) -> None:
    """Explicit logical conditions must not be silently omitted by AP projection."""
    values = {"inverse": "text", "has_member": {"equals_string": "x"}, "all_members": {"equals_string": "x"}}
    schema["classes"]["OntologyMetadata"]["attributes"]["reference"][field] = values.get(field, True)
    with pytest.raises(ValueError, match="Annotation property.*cannot be used"):
        _graph(schema)


@pytest.mark.parametrize("flag", ["identifier", "key"])
def test_annotation_identity_flags_keep_instance_semantics(schema: dict, flag: str) -> None:
    """Identity flags retain runtime requiredness and RDF identity while omitting OWL cardinalities."""
    slot = schema["classes"]["OntologyMetadata"]["attributes"]["reference"]
    slot[flag] = True
    slot.pop("required")
    source = yaml.safe_dump(schema)
    generator = _generator(schema)
    graph = Graph().parse(data=generator.serialize(), format="turtle")
    _assert_annotation_roles(graph)
    assert not list(graph.triples((None, OWL.hasKey, None)))
    assert getattr(generator.schemaview.induced_slot("reference", "OntologyMetadata"), flag)
    module = PythonGenerator(source).compile_module()
    instance = module.OntologyMetadata(reference=EX + "target", text="text")
    assert str(instance.reference) == EX + "target"
    with pytest.raises(ValueError, match="reference must be supplied"):
        module.OntologyMetadata(text="text")
    output = json.loads(JsonSchemaGenerator(source, top_class="OntologyMetadata").serialize())
    jsonschema.validate({"reference": EX + "target", "text": "text"}, output)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"text": "text"}, output)
    if flag == "identifier":
        context = ContextGenerator(source).serialize()
        data = Graph().parse(data=json_dumper.dumps(instance, contexts=context), format="json-ld")
        assert (URIRef(EX + "target"), RDF.type, URIRef(EX + "OntologyMetadata")) in data
        assert (URIRef(EX + "target"), URIRef(EX + "text"), Literal("text")) in data


@pytest.mark.parametrize(
    "condition",
    [
        "slot_conditions",
        "any_of",
        "all_of",
        "none_of",
        "exactly_one_of",
        "rules",
        "classification_rules",
        "unique_keys",
    ],
)
def test_logical_class_conditions_fail(schema: dict, condition: str) -> None:
    """Nested expressions, rules and keys cannot lose an AP condition."""
    cls = schema["classes"]["OntologyMetadata"]
    expression = {"slot_conditions": {"reference": {"equals_string": "ex:target"}}}
    if condition == "unique_keys":
        cls[condition] = {"key": {"unique_key_slots": ["reference"]}}
    elif condition == "rules":
        cls[condition] = [{"preconditions": expression, "postconditions": expression}]
    elif condition == "slot_conditions":
        cls.update(expression)
    else:
        cls[condition] = [expression]
    with pytest.raises(ValueError, match="Annotation property.*cannot be used"):
        _graph(schema)


@pytest.mark.parametrize("helper", ["_some_values_from", "_has_value", "_add_cardinality_restriction"])
def test_direct_iri_restriction_helpers_reject_ap(schema: dict, helper: str) -> None:
    """Helpers used outside slot translation honor the same role registry."""
    generator = _generator(schema)
    generator.as_graph()
    args = (OWL.minCardinality, 1) if helper == "_add_cardinality_restriction" else (URIRef(EX + "target"),)
    with pytest.raises(ValueError, match="Annotation property.*cannot be used"):
        getattr(generator, helper)(URIRef(EX + "reference"), *args)


@pytest.mark.parametrize("helper", ["_some_values_from", "_has_value", "_add_cardinality_restriction"])
@pytest.mark.parametrize("annotation_first", [False, True])
def test_synthetic_logical_use_conflicts_in_either_order(schema: dict, helper: str, annotation_first: bool) -> None:
    """Synthetic restrictions and strict AP emissions cannot acquire contradictory roles in either order."""
    generator = _generator(schema)
    generator.as_graph()
    predicate = URIRef(EX + "synthetic")
    args = (OWL.minCardinality, 1) if helper == "_add_cardinality_restriction" else (URIRef(EX + "target"),)
    if annotation_first:
        generator._emit_annotation(URIRef(EX + "model"), predicate, Literal("text"), "declared metadata")
        with pytest.raises(ValueError, match="Annotation property.*synthetic.*cannot be used"):
            getattr(generator, helper)(predicate, *args)
    else:
        getattr(generator, helper)(predicate, *args)
        assert list(generator.graph.subjects(OWL.onProperty, predicate))
        with pytest.raises(ValueError, match="Conflicting OWL property roles.*synthetic"):
            generator._emit_annotation(URIRef(EX + "model"), predicate, Literal("text"), "declared metadata")


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("owner", ["ontology", "Annotated", "ZAnnotated"])
def test_declared_annotation_cannot_retype_synthetic_mixins(schema: dict, native: bool, owner: str) -> None:
    """Mapped metadata cannot turn an already used synthetic mixin predicate into an AP."""
    schema["classes"]["OntologyMetadata"]["attributes"]["reference"]["slot_uri"] = "linkml:mixins"
    schema["classes"].update({"Marker": {"mixin": True}, "Thing": {"mixins": ["Marker"]}})
    if owner != "ontology":
        del schema["annotations"]["reference"]
        schema["classes"][owner] = {
            "instantiates": ["ex:OntologyMetadata"],
            "annotations": {"reference": "ex:target"},
        }
    with pytest.raises(ValueError, match="(Annotation property|Conflicting OWL property roles).*linkml/mixins"):
        _graph(schema, use_native_uris=native, mixins_as_expressions=True)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("owner", ["ontology", "Annotated", "ZAnnotated"])
def test_ordinary_synthetic_mixins_keep_legacy_metadata(schema: dict, native: bool, owner: str) -> None:
    """Early and late legacy metadata preserve ordinary mixin restrictions and original literal values."""
    schema["classes"].update({"Marker": {"mixin": True}, "Thing": {"mixins": ["Marker"]}})
    annotations = {"linkml:mixins": "intentional text", "ex:legacy_note": "annotation text"}
    subject = URIRef(EX + "model") if owner == "ontology" else URIRef(EX + owner)
    if owner == "ontology":
        schema["annotations"].update(annotations)
    else:
        schema["classes"][owner] = {"annotations": annotations}
    graph = _graph(schema, use_native_uris=native, mixins_as_expressions=True)
    predicate = URIRef("https://w3id.org/linkml/mixins")
    assert len(list(graph.subjects(OWL.onProperty, predicate))) == 2
    assert (subject, predicate, Literal("intentional text")) in graph
    assert (predicate, RDF.type, OWL.AnnotationProperty) not in graph
    assert (subject, URIRef(EX + "legacy_note"), Literal("annotation text")) in graph
    assert (URIRef(EX + "legacy_note"), RDF.type, OWL.AnnotationProperty) in graph
    _assert_annotation_roles(graph)


@pytest.mark.parametrize("native", [False, True])
def test_legacy_annotation_finalization_is_repeatable(schema: dict, native: bool) -> None:
    """Each generation resets candidates without changing the source or inherited AP declarations."""
    schema["classes"].update(
        {
            "Annotated": {"annotations": {"linkml:mixins": "intentional text", "ex:legacy_note": "text"}},
            "Marker": {"mixin": True},
            "Thing": {"mixins": ["Marker"]},
            "ChildMetadata": {"is_a": "OntologyMetadata"},
        }
    )
    generator = _generator(schema, use_native_uris=native, mixins_as_expressions=True)
    before = as_dict(generator.schemaview.schema)
    first = generator.serialize()
    assert as_dict(generator.schemaview.schema) == before
    # An emission on the completed graph must not carry candidates into the next run.
    generator._emit_annotation(
        URIRef(EX + "Annotated"), URIRef(EX + "transient"), Literal("text"), "extra", legacy=True
    )
    assert generator.serialize() == first
    assert as_dict(generator.schemaview.schema) == before
    _assert_annotation_roles(generator.as_graph())
    assert generator.serialize() == first


@pytest.mark.parametrize("annotation_first", [False, True])
def test_legacy_candidate_does_not_hide_strict_role_collision(schema: dict, annotation_first: bool) -> None:
    """A pending legacy declaration cannot defer a strict annotation's collision with logical use."""
    generator = _generator(schema)
    generator.as_graph()
    predicate = URIRef(EX + "synthetic")
    subject = URIRef(EX + "model")
    generator._emit_annotation(subject, predicate, Literal("legacy text"), "legacy metadata", legacy=True)
    if annotation_first:
        generator._emit_annotation(subject, predicate, Literal("declared text"), "declared metadata")
        with pytest.raises(ValueError, match="Annotation property.*synthetic.*cannot be used"):
            generator._some_values_from(predicate, URIRef(EX + "target"))
    else:
        generator._some_values_from(predicate, URIRef(EX + "target"))
        with pytest.raises(ValueError, match="Conflicting OWL property roles.*synthetic"):
            generator._emit_annotation(subject, predicate, Literal("declared text"), "declared metadata")


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("configured", [False, True])
def test_type_object_value_role_repeats(schema: dict, native: bool, configured: bool) -> None:
    """The actual synthetic datatype property and its restrictions survive every generation."""
    predicate = URIRef(EX + "custom_value" if configured else "https://w3id.org/linkml/topValue")
    tag = "ex:custom_value" if configured else "linkml:topValue"
    schema["types"] = {"Count": {"uri": "xsd:integer", "base": "int"}}
    schema["classes"]["Annotated"] = {"annotations": {tag: "intentional text"}}
    generator = _generator(
        schema, use_native_uris=native, type_objects=True, top_value_uri=predicate if configured else None
    )
    before = as_dict(generator.schemaview.schema)
    first = generator.serialize()
    for serialized in [first, generator.serialize(), generator.serialize()]:
        assert serialized == first
        graph = Graph().parse(data=serialized, format="turtle")
        assert (predicate, RDF.type, OWL.DatatypeProperty) in graph
        assert (predicate, RDFS.label, Literal("value")) in graph
        assert (URIRef(EX + "Annotated"), predicate, Literal("intentional text")) in graph
        restrictions = list(graph.objects(URIRef(EX + "Count"), RDFS.subClassOf))
        assert len(restrictions) == 1
        assert (restrictions[0], OWL.onProperty, predicate) in graph
        assert (restrictions[0], OWL.qualifiedCardinality, Literal(1)) in graph
        assert (restrictions[0], OWL.onDataRange, URIRef(EX + "Count")) in graph
        _assert_annotation_roles(graph)
    assert as_dict(generator.schemaview.schema) == before


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("predicate", [EX + "reference", str(RDFS.label)])
def test_preconfigured_type_value_cannot_use_annotation_property(schema: dict, native: bool, predicate: str) -> None:
    """A caller-supplied synthetic property IRI cannot bypass explicit or built-in AP roles."""
    schema["types"] = {"Count": {"uri": "xsd:integer", "base": "int"}}
    generator = _generator(schema, use_native_uris=native, type_objects=True, top_value_uri=URIRef(predicate))
    for _ in range(2):
        with pytest.raises(ValueError, match="Conflicting OWL property roles.*" + predicate):
            generator.serialize()


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("owner", ["ontology", "Annotated"])
def test_declared_annotation_cannot_retype_type_object_value(schema: dict, native: bool, owner: str) -> None:
    """Strict mapped annotations reject the synthetic DP whether emitted before or after add_type."""
    schema["types"] = {"Count": {"uri": "xsd:integer", "base": "int"}}
    schema["classes"]["OntologyMetadata"]["attributes"]["reference"]["slot_uri"] = "linkml:topValue"
    if owner != "ontology":
        del schema["annotations"]["reference"]
        schema["classes"][owner] = {
            "instantiates": ["ex:OntologyMetadata"],
            "annotations": {"reference": "ex:target"},
        }
    with pytest.raises(ValueError, match="Conflicting OWL property roles.*linkml/topValue"):
        _graph(schema, use_native_uris=native, type_objects=True)


def _shadowed_rule_schema(schema: dict, nested: bool, annotation_attribute: bool = False) -> dict:
    """Model independent global and attribute declarations sharing a name, with an actual class rule."""
    schema = deepcopy(schema)
    schema["slots"] = {
        "shared": {"slot_uri": "ex:metadata", "range": "string", "implements": ["owl:AnnotationProperty"]}
    }
    attribute = {"slot_uri": "ex:shadowed", "range": "string"}
    if annotation_attribute:
        attribute["implements"] = ["owl:AnnotationProperty"]

    def condition(value: str) -> dict:
        """Exercise both anonymous class and slot-expression recursion."""
        slot = {"all_of": [{"equals_string": value}]} if nested else {"equals_string": value}
        expression = {"slot_conditions": {"shared": slot}}
        return {"all_of": [expression]} if nested else expression

    schema["classes"]["Data"] = {
        "attributes": {"shared": attribute},
        "rules": [{"preconditions": condition("x"), "postconditions": condition("y")}],
    }
    return schema


@pytest.mark.parametrize("nested", [False, True])
def test_rule_uses_shadowing_attribute_declaration(schema: dict, nested: bool) -> None:
    """Rules use their owning class's logical attribute, including its non-default mapped IRI."""
    graph = _graph(_shadowed_rule_schema(schema, nested))
    assert (URIRef(EX + "metadata"), RDF.type, OWL.AnnotationProperty) in graph
    assert (URIRef(EX + "shadowed"), RDF.type, OWL.DatatypeProperty) in graph
    restrictions = list(graph.subjects(OWL.onProperty, URIRef(EX + "shadowed")))
    # Preserve the existing nested-class quantifier default; this correction
    # concerns ownership and the actual predicate selected by the rule.
    quantifier = OWL.allValuesFrom if nested else OWL.someValuesFrom
    conditions = {}
    for node in restrictions:
        for filler in graph.objects(node, quantifier):
            for facets in graph.objects(filler, OWL.withRestrictions):
                for facet in graph.items(facets):
                    for value in graph.objects(facet, XSD.pattern):
                        conditions[value] = node
    assert set(conditions) == {Literal("x"), Literal("y")}
    assert len(set(conditions.values())) == 2
    _assert_annotation_roles(graph)


@pytest.mark.parametrize("nested", [False, True])
def test_rule_rejects_annotation_attribute_selected_by_owner(schema: dict, nested: bool) -> None:
    """An actual AP selected in a rule still fails, with the owning attribute's IRI in the diagnostic."""
    with pytest.raises(ValueError, match="Annotation property https://example.org/shadowed cannot be used"):
        _graph(_shadowed_rule_schema(schema, nested, annotation_attribute=True))


def test_rule_shadowing_cannot_hide_native_iri_role_collision(schema: dict) -> None:
    """Native URIs still reject the genuinely shared output IRI of global AP and logical attribute."""
    with pytest.raises(ValueError, match="Conflicting OWL property roles.*https://example.org/shared"):
        _graph(_shadowed_rule_schema(schema, nested=True), use_native_uris=True)


@pytest.mark.parametrize(
    "predicate",
    [
        str(OWL.imports),
        str(OWL.versionIRI),
        str(OWL.equivalentClass),
        str(OWL) + "totallyUnknown",
        str(RDF) + "unknown",
        str(RDFS) + "unknown",
        str(XSD.string),
    ],
)
@pytest.mark.parametrize("declared", [False, True])
def test_reserved_annotation_predicates_fail(schema: dict, predicate: str, declared: bool) -> None:
    """OWL 2's entire reserved namespace boundary applies, including unknown names."""
    if declared:
        schema["classes"]["OntologyMetadata"]["attributes"]["reference"]["slot_uri"] = predicate
    else:
        schema["annotations"][predicate] = "ex:target"
    with pytest.raises(ValueError, match="Unsupported structural predicate"):
        _graph(schema)


def test_builtin_annotation_boundary(schema: dict) -> None:
    """Table 5's complete nine APs are admitted; structural header IRIs are excluded."""
    expected = {
        RDFS.label,
        RDFS.comment,
        RDFS.seeAlso,
        RDFS.isDefinedBy,
        OWL.deprecated,
        OWL.versionInfo,
        OWL.priorVersion,
        OWL.backwardCompatibleWith,
        OWL.incompatibleWith,
    }
    assert OwlSchemaGenerator._BUILTIN_ANNOTATION_PROPERTIES == expected
    assert not {OWL.imports, OWL.versionIRI, OWL.equivalentClass} & expected
    schema["prefixes"]["rdfs"] = str(RDFS)
    schema["annotations"].update(
        {
            "rdfs:" + str(predicate).removeprefix(str(RDFS))
            if str(predicate).startswith(str(RDFS))
            else "owl:" + str(predicate).removeprefix(str(OWL)): "text"
            for predicate in expected
        }
    )
    graph = _graph(schema)
    for predicate in expected:
        assert (URIRef(EX + "model"), predicate, Literal("text")) in graph


@pytest.mark.parametrize("predicate", sorted(OwlSchemaGenerator._BUILTIN_ANNOTATION_PROPERTIES))
@pytest.mark.parametrize("native", [False, True])
def test_builtin_role_uses_actual_output_iri(schema: dict, predicate: URIRef, native: bool) -> None:
    """Every specification-defined AP gets its role implicitly only at its actual output IRI."""
    schema["classes"]["Data"] = {"attributes": {"value": {"slot_uri": str(predicate), "range": "string"}}}
    graph = _graph(schema, use_native_uris=native)
    actual = URIRef(EX + "value") if native else predicate
    role = OWL.DatatypeProperty if native else OWL.AnnotationProperty
    assert (actual, RDF.type, role) in graph
    assert bool(list(graph.subjects(OWL.onProperty, actual))) == native
    _assert_annotation_roles(graph)


@pytest.mark.parametrize("predicate", sorted(OwlSchemaGenerator._BUILTIN_ANNOTATION_PROPERTIES))
@pytest.mark.parametrize("role", ["owl:ObjectProperty", "owl:DatatypeProperty"])
def test_explicit_wrong_builtin_role_fails(schema: dict, predicate: URIRef, role: str) -> None:
    """The normative built-in boundary rejects contradictory explicit logical roles."""
    schema["classes"]["Data"] = {
        "attributes": {"value": {"slot_uri": str(predicate), "range": "string", "implements": [role]}}
    }
    with pytest.raises(ValueError, match="Conflicting OWL property roles"):
        _graph(schema)


def test_legal_global_annotation_axioms(schema: dict) -> None:
    """Annotation domain/range are named IRIs and subproperties preserve AP roles."""
    schema["slots"] = {
        "parent": {"implements": ["owl:AnnotationProperty"], "range": "string"},
        "child": {
            "is_a": "parent",
            "implements": ["owl:AnnotationProperty"],
            "range": "string",
            "domain": "OntologyMetadata",
            "pattern": "^x$",
        },
    }
    graph = _graph(schema)
    assert (URIRef(EX + "child"), RDFS.subPropertyOf, URIRef(EX + "parent")) in graph
    assert (URIRef(EX + "child"), RDFS.domain, URIRef(EX + "OntologyMetadata")) in graph
    assert (URIRef(EX + "child"), RDFS.range, XSD.string) in graph
    _assert_annotation_roles(graph)


def test_anonymous_global_annotation_range_fails(schema: dict) -> None:
    """Annotation-property ranges cannot reuse anonymous logical range builders."""
    schema["slots"] = {"value": {"implements": ["owl:AnnotationProperty"], "any_of": [{"range": "string"}]}}
    with pytest.raises(ValueError, match="requires a named IRI range"):
        _graph(schema)


@pytest.mark.parametrize("role", ["owl:ObjectProperty", "owl:DatatypeProperty"])
@pytest.mark.parametrize("literal", [False, True])
def test_enum_membership_preserves_declared_data_role(schema: dict, role: str, literal: bool) -> None:
    """The LinkML enum relation retains a schema data role and rejects incompatible RDF values."""
    schema["slots"] = {"membership": {"slot_uri": "linkml:permissible_values", "range": "string", "implements": [role]}}
    schema["enums"] = {
        "Choice": {
            "implements": ["rdfs:Literal"] if literal else ["owl:Class"],
            "permissible_values": {"A": {"meaning": "ex:A"}},
        }
    }
    if literal != (role == "owl:DatatypeProperty"):
        with pytest.raises(ValueError, match="Conflicting OWL property roles.*permissible_values"):
            _graph(schema)
    else:
        graph = _graph(schema)
        predicate = URIRef("https://w3id.org/linkml/permissible_values")
        expected = Literal("A") if literal else URIRef(EX + "A")
        assert (URIRef(EX + "Choice"), predicate, expected) in graph
        assert (predicate, RDF.type, OWL.AnnotationProperty) not in graph
        assert (predicate, RDF.type, URIRef(str(OWL) + role.split(":")[1])) in graph


def _mixed_enum_schema(schema: dict, role: str | None) -> dict:
    """Declare mixed PV kinds and an optional independent schema role for their membership predicate."""
    schema = deepcopy(schema)
    schema["prefixes"]["dcterms"] = str(DCTERMS)
    schema["classes"]["Thing"] = {}
    schema["enums"] = {
        "Mixed": {
            "permissible_values": {
                "C": {"meaning": "ex:C", "implements": ["owl:Class"]},
                "I": {"meaning": "ex:I", "implements": ["owl:NamedIndividual"]},
            }
        }
    }
    if role is not None:
        schema["slots"] = {"member_of": {"slot_uri": "dcterms:isPartOf", "range": "Thing", "implements": [role]}}
        schema["classes"]["Carrier"] = {"slots": ["member_of"]}
    return schema


@pytest.mark.parametrize("role", [None, "owl:AnnotationProperty", "owl:ObjectProperty"])
@pytest.mark.parametrize("native", [False, True])
def test_mixed_enum_membership_respects_existing_role(schema: dict, role: str | None, native: bool) -> None:
    """Mixed enums preserve membership triples, logical restrictions, and independent AP projections."""
    graph = _graph(_mixed_enum_schema(schema, role), use_native_uris=native)
    for name in ["C", "I"]:
        assert (URIRef(EX + name), DCTERMS.isPartOf, URIRef(EX + "Mixed")) in graph
    logical_membership = role == "owl:ObjectProperty" and not native
    assert ((DCTERMS.isPartOf, RDF.type, OWL.AnnotationProperty) in graph) == (not logical_membership)
    if role == "owl:ObjectProperty":
        predicate = URIRef(EX + "member_of") if native else DCTERMS.isPartOf
        assert (predicate, RDF.type, OWL.ObjectProperty) in graph
        assert (predicate, RDFS.range, URIRef(EX + "Thing")) in graph
        assert list(graph.subjects(OWL.onProperty, predicate))
    _assert_annotation_roles(graph)


def test_declared_ap_metadata_still_conflicts_with_mixed_enum_data_role(schema: dict) -> None:
    """Legacy synthetic membership does not relax strict declared metaclass annotation collisions."""
    schema = _mixed_enum_schema(schema, "owl:ObjectProperty")
    schema["classes"]["OntologyMetadata"]["attributes"]["reference"]["slot_uri"] = "dcterms:isPartOf"
    with pytest.raises(ValueError, match="Conflicting OWL property roles.*isPartOf"):
        _graph(schema)


def test_logical_subproperty_of_annotation_fails(schema: dict) -> None:
    """Explicitly overriding an AP parent's role does not produce a cross-role axiom."""
    schema["slots"] = {
        "parent": {"implements": ["owl:AnnotationProperty"], "range": "string"},
        "child": {"is_a": "parent", "implements": ["owl:DatatypeProperty"], "range": "string"},
    }
    with pytest.raises(ValueError, match="Annotation property.*logical subproperty"):
        _graph(schema)


def test_ordinary_expression_inference_and_contextual_enum(schema: dict) -> None:
    """Expression-only DP inference and local enum refinements keep their prior declarations."""
    schema.pop("annotations")
    schema.pop("instantiates")
    schema["slots"] = {
        "union_value": {"any_of": [{"range": "string"}, {"range": "integer"}]},
        "text_value": {"range": "string"},
        "unconstrained": {},
    }
    schema["enums"] = {"Choice": {"permissible_values": {"A": {}}}}
    schema["classes"] = {
        "Data": {"slots": ["union_value", "text_value"], "slot_usage": {"text_value": {"range": "Choice"}}}
    }
    graph = _graph(schema)
    assert (URIRef(EX + "union_value"), RDF.type, OWL.DatatypeProperty) in graph
    assert (URIRef(EX + "text_value"), RDF.type, OWL.DatatypeProperty) in graph
    assert list(graph.subjects(OWL.onProperty, URIRef(EX + "union_value")))
    schema["default_range"] = "string"
    graph = _graph(schema)
    assert not list(graph.objects(URIRef(EX + "unconstrained"), RDFS.range))


def test_same_name_attributes_use_their_own_iris(schema: dict) -> None:
    """Two attributes with the same name may have distinct mapped predicates and roles."""
    schema["classes"]["Data"] = {"attributes": {"reference": {"slot_uri": "ex:data_reference", "range": "string"}}}
    graph = _graph(schema)
    assert (URIRef(EX + "data_reference"), RDF.type, OWL.DatatypeProperty) in graph
    assert list(graph.subjects(OWL.onProperty, URIRef(EX + "data_reference")))
    _assert_annotation_roles(graph)


@pytest.mark.parametrize("equivalent", [False, True])
def test_class_mappings_and_ols_intent(schema: dict, equivalent: bool) -> None:
    """Mapping and OLS annotations are declared; structural equivalence stays structural."""
    schema["classes"]["OntologyMetadata"]["class_uri"] = "ex:Mapped"
    graph = _graph(
        schema, use_native_uris=True, assert_equivalent_classes=equivalent, metadata_profile=MetadataProfile.ols
    )
    if equivalent:
        assert (URIRef(EX + "OntologyMetadata"), OWL.equivalentClass, URIRef(EX + "Mapped")) in graph
        assert (OWL.equivalentClass, RDF.type, OWL.AnnotationProperty) not in graph
    else:
        assert (SKOS.exactMatch, RDF.type, OWL.AnnotationProperty) in graph
    assert (URIRef("http://purl.obolibrary.org/obo/IAO_0000700"), RDF.type, OWL.AnnotationProperty) in graph


def test_cli_and_api_defaults(schema: dict, tmp_path: Path) -> None:
    """Default API and explicit CLI options retain the same declared annotation terms."""
    source = tmp_path / "model.yaml"
    source.write_text(yaml.safe_dump(schema))
    api_graph = Graph().parse(data=OwlSchemaGenerator(source).serialize(), format="turtle")
    _assert_annotation_roles(api_graph)
    result = CliRunner().invoke(cli, [str(source), "--no-type-objects", "--no-metaclasses", "--no-use-native-uris"])
    assert result.exit_code == 0, result.output
    cli_graph = Graph().parse(data=result.output, format="turtle")
    assert URIRef(EX + "target") in cli_graph.objects(None, URIRef(EX + "reference"))
    _assert_annotation_roles(cli_graph)


def _data(reference: object, text: object) -> Graph:
    """Construct actual metadata-class instances with chosen RDF value kinds."""
    graph = Graph()
    node = URIRef(EX + "instance")
    graph.add((node, RDF.type, URIRef(EX + "OntologyMetadata")))
    graph.add((node, URIRef(EX + "reference"), reference))
    graph.add((node, URIRef(EX + "text"), text))
    return graph


@pytest.mark.parametrize("valid", [True, False])
def test_shacl_instance_constraints_and_shape_annotations(schema: dict, valid: bool) -> None:
    """OWL AP projection leaves SHACL metadata-instance validation and shape annotations intact."""
    schema["classes"]["Thing"] = {"instantiates": schema["instantiates"], "annotations": schema["annotations"]}
    output = ShaclGenerator(yaml.safe_dump(schema), include_annotations=True).serialize()
    graph = Graph().parse(data=output, format="turtle")
    shape = next(graph.subjects(SH.targetClass, URIRef(EX + "Thing")))
    assert (shape, URIRef(EX + "reference"), URIRef(EX + "target")) in graph
    data = _data(URIRef(EX + "target") if valid else Literal("ex:target"), Literal("text"))
    assert validate(data, shacl_graph=graph, meta_shacl=True)[0] == valid
    data = _data(URIRef(EX + "target"), Literal("text") if valid else URIRef(EX + "text"))
    assert validate(data, shacl_graph=graph, meta_shacl=True)[0] == valid


def test_jsonschema_metadata_instances(schema: dict) -> None:
    """JSON accepts strings for both ranges and rejects a number without promising RDF node kinds."""
    output = json.loads(JsonSchemaGenerator(yaml.safe_dump(schema), top_class="OntologyMetadata").serialize())
    jsonschema.validate({"reference": EX + "target", "text": "text"}, output)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"reference": 42, "text": "text"}, output)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"reference": EX + "target"}, output)


@pytest.mark.parametrize("valid", [True, False])
def test_shex_real_metadata_instances(schema: dict, valid: bool) -> None:
    """A real ShEx consumer enforces the original nodeidentifier/string instance contract."""
    output = ShExGenerator(yaml.safe_dump(schema)).serialize()
    data = _data(URIRef(EX + "target") if valid else Literal("text"), Literal("text"))
    results = ShExEvaluator(rdf=data, schema=output, focus=EX + "instance", start=EX + "OntologyMetadata").evaluate()
    assert results and all(result.result == valid for result in results), results


def test_generated_python_and_schema_runtime(schema: dict, tmp_path: Path) -> None:
    """Generated Python retains instance fields; loading a schema preserves declarations and metadata."""
    source = tmp_path / "model.yaml"
    source.write_text(yaml.safe_dump(schema))
    module = PythonGenerator(source).compile_module()
    instance = yaml_loader.load({"reference": EX + "target", "text": "text"}, target_class=module.OntologyMetadata)
    assert str(instance.reference) == EX + "target"
    assert instance.text == "text"
    with pytest.raises(ValueError, match="reference must be supplied"):
        module.OntologyMetadata(text="text")
    view = SchemaView(source)
    slot = view.induced_slot("reference", "OntologyMetadata")
    assert slot.range == "nodeidentifier"
    assert slot.implements == ["owl:AnnotationProperty"]
    assert view.schema.annotations["reference"].value == "ex:target"
    # Python YAMLRoot intentionally coerces string fields; it is not JSON Schema validation.
    coerced = module.OntologyMetadata(reference=EX + "target", text=42)
    assert coerced.text == "42"


def test_rdf_jsonld_preserve_schema_metadata(schema: dict) -> None:
    """Schema serialization keeps LinkML annotation objects, their original values, and implements."""
    import linkml_runtime

    context = Path(linkml_runtime.__file__).parent / "linkml_model/jsonld/meta.context.jsonld"
    view = SchemaView(yaml.safe_dump(schema))
    view.merge_imports()
    view.schema.imports = []
    encoded = JSONLDGenerator(view.schema, metamodel_context=str(context)).serialize()
    graph = Graph().parse(data=encoded, format="json-ld")
    rdf = Graph().parse(data=RDFGenerator(view.schema).serialize(context=[str(context)]), format="turtle")
    linkml = "https://w3id.org/linkml/"
    for artifact in [graph, rdf]:
        # Annotation.value is mapped to skos:example by the vendored metamodel context.
        assert Literal("ex:target") in artifact.objects(None, SKOS.example)
        assert Literal("https://example.org/a-textual-label") in artifact.objects(None, SKOS.example)
        assert list(artifact.triples((None, URIRef(linkml + "instantiates"), None)))
        assert list(artifact.triples((None, URIRef(linkml + "implements"), None)))
        assert (URIRef(EX + "model"), URIRef(EX + "reference"), URIRef(EX + "target")) not in artifact


@pytest.fixture
def owlapi_classpath() -> str:
    """Require a prepared dependency tree in the dedicated CI job; never fetch from pytest."""
    filename = os.environ.get("LINKML_OWLAPI_CLASSPATH_FILE")
    if not filename:
        if os.environ.get("LINKML_REQUIRE_OWLAPI") == "1":
            pytest.fail("Required OWLAPI gate has no LINKML_OWLAPI_CLASSPATH_FILE")
        pytest.skip("OWLAPI external consumer runs in its dedicated CI job with a prepared classpath")
    classpath = Path(filename).read_text().strip()
    assert classpath, "Empty prepared OWLAPI classpath"
    return classpath


def _probe(schema: dict, tmp_path: Path, classpath: str, rows: list[list[str]], **options: object) -> None:
    """Run the real Java consumer on direct generated output and check its round-trip verdict."""
    source = tmp_path / "generated.ttl"
    serialized = _generator(schema, **options).serialize()
    source.write_text(serialized)
    _assert_annotation_roles(Graph().parse(data=serialized, format="turtle"))
    expectations = tmp_path / "expected.tsv"
    expectations.write_text("\n".join("\t".join(row) for row in rows) + "\n")
    result = subprocess.run(
        [
            "java",
            "--class-path",
            classpath,
            str(HARNESS / "AnnotationProbe.java"),
            str(source),
            str(tmp_path / "roundtrip.ttl"),
            str(expectations),
        ],
        check=True,
    )
    assert result.returncode == 0


@pytest.mark.integration
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("type_objects", [False, True])
def test_owlapi_documentation_roundtrip(
    schema: dict, tmp_path: Path, owlapi_classpath: str, native: bool, type_objects: bool
) -> None:
    """The published generic example has zero profile violations and retains both header values."""
    rows = [
        ["ontology", EX + "reference", "IRI", EX + "target", "", ""],
        ["ontology", EX + "text", "LITERAL", EX + "a-textual-label", "", ""],
    ]
    _probe(schema, tmp_path, owlapi_classpath, rows, use_native_uris=native, type_objects=type_objects)


@pytest.mark.integration
def test_owlapi_non_header_owners(schema: dict, tmp_path: Path, owlapi_classpath: str) -> None:
    """Class, slot, type, enum and PV annotation assertions survive a real OWLAPI round-trip."""
    metadata = {"instantiates": schema["instantiates"], "annotations": schema["annotations"]}
    schema["classes"]["Thing"] = deepcopy(metadata)
    schema["slots"] = {"value": {"range": "string", **deepcopy(metadata)}}
    # The existing custom typeof-only mapping emits a singleton DataIntersectionOf.
    # A direct datatype URI isolates annotation retention from that unrelated profile defect.
    schema["types"] = {"Count": {"uri": "xsd:integer", "base": "int", **deepcopy(metadata)}}
    schema["enums"] = {
        "Choice": {**deepcopy(metadata), "permissible_values": {"A": {"meaning": "ex:A", **deepcopy(metadata)}}}
    }
    rows = [
        [owner, EX + "reference", "IRI", EX + "target", "", ""]
        for owner in ["ontology", EX + "Thing", EX + "value", str(XSD.integer), EX + "Choice", EX + "A"]
    ]
    _probe(schema, tmp_path, owlapi_classpath, rows)


@pytest.mark.integration
def test_owlapi_implicit_builtin_identifier(schema: dict, tmp_path: Path, owlapi_classpath: str) -> None:
    """An implicit built-in AP with a LinkML identifier survives the same strict consumer gate."""
    schema["prefixes"]["rdfs"] = str(RDFS)
    schema["classes"]["Data"] = {
        "attributes": {"label": {"slot_uri": "rdfs:label", "range": "string", "identifier": True}},
        "annotations": {"rdfs:label": "Human label"},
    }
    rows = [
        ["ontology", EX + "reference", "IRI", EX + "target", "", ""],
        ["ontology", EX + "text", "LITERAL", EX + "a-textual-label", "", ""],
        [EX + "Data", str(RDFS.label), "LITERAL", "Human label", "", ""],
    ]
    _probe(schema, tmp_path, owlapi_classpath, rows)


@pytest.mark.integration
@pytest.mark.parametrize("predicate", [EX + "reference", str(RDFS.label)])
def test_owlapi_unused_preconfigured_type_value(
    schema: dict, tmp_path: Path, owlapi_classpath: str, predicate: str
) -> None:
    """A configured IRI retains its legal AP role when no synthetic value property is actually emitted."""
    rows = [
        ["ontology", EX + "reference", "IRI", EX + "target", "", ""],
        ["ontology", EX + "text", "LITERAL", EX + "a-textual-label", "", ""],
    ]
    _probe(schema, tmp_path, owlapi_classpath, rows, type_objects=True, top_value_uri=URIRef(predicate))


@pytest.mark.integration
@pytest.mark.parametrize("owner", ["ontology", "Annotated", "ZAnnotated"])
def test_owlapi_finalized_legacy_annotations(schema: dict, tmp_path: Path, owlapi_classpath: str, owner: str) -> None:
    """Finalized genuine APs retain early/late class and ontology values through the real consumer."""
    annotations = {"ex:legacy_note": "annotation text"}
    if owner == "ontology":
        schema["annotations"].update(annotations)
    else:
        schema["classes"][owner] = {"annotations": annotations}
    rows = [
        ["ontology", EX + "reference", "IRI", EX + "target", "", ""],
        ["ontology", EX + "text", "LITERAL", EX + "a-textual-label", "", ""],
        ["ontology" if owner == "ontology" else EX + owner, EX + "legacy_note", "LITERAL", "annotation text", "", ""],
    ]
    _probe(schema, tmp_path, owlapi_classpath, rows)


@pytest.mark.integration
def test_owlapi_rule_with_shadowing_attribute(schema: dict, tmp_path: Path, owlapi_classpath: str) -> None:
    """A nested rule on a logical attribute shadowing a global AP passes the real profile/round-trip gate."""
    rows = [
        ["ontology", EX + "reference", "IRI", EX + "target", "", ""],
        ["ontology", EX + "text", "LITERAL", EX + "a-textual-label", "", ""],
    ]
    _probe(_shadowed_rule_schema(schema, nested=True), tmp_path, owlapi_classpath, rows)


@pytest.mark.integration
@pytest.mark.parametrize("logical", [False, True])
def test_owlapi_mixed_enum_membership(schema: dict, tmp_path: Path, owlapi_classpath: str, logical: bool) -> None:
    """The actual mixed-enum membership assertions survive both OWLAPI load and reload."""
    rows = [
        ["ontology", EX + "reference", "IRI", EX + "target", "", ""],
        ["ontology", EX + "text", "LITERAL", EX + "a-textual-label", "", ""],
    ]
    if not logical:
        rows.extend([[EX + name, str(DCTERMS.isPartOf), "IRI", EX + "Mixed", "", ""] for name in ["C", "I"]])
    _probe(_mixed_enum_schema(schema, "owl:ObjectProperty" if logical else None), tmp_path, owlapi_classpath, rows)
    if logical:
        # The shared probe checks profile validity and annotations. Independently
        # assert the retained object-property assertions in both emitted documents.
        java_source = tmp_path / "MembershipProbe.java"
        java_source.write_text("""
import java.io.File;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.IRI;

class MembershipProbe {
    public static void main(String[] args) throws Exception {
        for (var path : args) {
            var manager = OWLManager.createOWLOntologyManager();
            var ontology = manager.loadOntologyFromOntologyDocument(new File(path));
            var factory = manager.getOWLDataFactory();
            var property = factory.getOWLObjectProperty(IRI.create("http://purl.org/dc/terms/isPartOf"));
            for (var subject : new String[] {"C", "I"}) {
                var assertion = factory.getOWLObjectPropertyAssertionAxiom(property,
                    factory.getOWLNamedIndividual(IRI.create("https://example.org/" + subject)),
                    factory.getOWLNamedIndividual(IRI.create("https://example.org/Mixed")));
                if (!ontology.containsAxiom(assertion)) {
                    throw new AssertionError("Missing mixed-enum membership in " + path + ": " + assertion);
                }
            }
        }
    }
}
""")
        subprocess.run(
            [
                "java",
                "--class-path",
                owlapi_classpath,
                str(java_source),
                str(tmp_path / "generated.ttl"),
                str(tmp_path / "roundtrip.ttl"),
            ],
            check=True,
        )
