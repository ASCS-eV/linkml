"""
Tests for SHACL Generator naming behavior and class-URI-based shape merging.

This extends the existing test_shaclgen.py module with:

1. Shape naming mode tests
2. Default merging behavior for classes sharing class_uri
3. Correct (non-merged) behavior when using native LinkML class names
"""

import pytest
import rdflib
from rdflib import RDF, SH
from rdflib.collection import Collection
from rdflib.compare import isomorphic

from linkml.generators.shaclgen import ShaclGenerator


# ---------------------------------------------------------------------------
# 1. SHAPE NAMING MODES: class_uri (default) vs native LinkML class names
# ---------------------------------------------------------------------------
def test_shacl_shape_naming_modes(tmp_path):
    """
    Validate naming modes using a minimal deterministic schema:

    - use_class_uri_names=True  (default)  => shape URIs based on class_uri
    - use_class_uri_names=False             => shape URIs based on LinkML class name

    A custom schema is used to guarantee differences.
    """

    test_schema = """
id: http://example.org/test
name: naming_test
prefixes:
  ex: http://example.org/
  linkml: https://w3id.org/linkml/
default_prefix: http://example.org/test#

imports:
  - linkml:types

classes:
  Foo:
    description: Test class Foo
    class_uri: ex:ExternalFoo
    slots:
      - a

  Bar:
    description: Test class Bar
    class_uri: ex:ExternalBar
    slots:
      - b

slots:
  a:
    range: string

  b:
    range: string
"""

    schema_path = tmp_path / "naming_test.yaml"
    schema_path.write_text(test_schema)

    # --- Mode 1: default mode = class_uri naming ---
    shacl_default = ShaclGenerator(str(schema_path), mergeimports=True, use_class_uri_names=True).serialize()

    g_default = rdflib.Graph()
    g_default.parse(data=shacl_default, format="turtle")
    default_shapes = {str(s) for s in g_default.subjects(RDF.type, SH.NodeShape)}

    # --- Mode 2: native names (LinkML class names) ---
    shacl_native = ShaclGenerator(str(schema_path), mergeimports=True, use_class_uri_names=False).serialize()

    g_native = rdflib.Graph()
    g_native.parse(data=shacl_native, format="turtle")
    native_shapes = {str(s) for s in g_native.subjects(RDF.type, SH.NodeShape)}

    # They must produce the same number of shapes
    assert len(default_shapes) == len(native_shapes) == 2

    # Default mode: shapes must come from class_uri
    assert any("ExternalFoo" in s for s in default_shapes)
    assert any("ExternalBar" in s for s in default_shapes)

    # Native mode: shapes must come from class names Foo and Bar
    assert any(s.endswith("Foo") for s in native_shapes)
    assert any(s.endswith("Bar") for s in native_shapes)

    # And finally: All default URIs MUST differ from all native URIs
    assert default_shapes.isdisjoint(native_shapes), (
        f"Expected naming modes to produce different URIs:\n{default_shapes}\nvs\n{native_shapes}"
    )


# ---------------------------------------------------------------------------
# 2. PROPERTY SHAPE CONSTRAINTS: sh:class (default) vs sh:node (native names)
# ---------------------------------------------------------------------------
def test_shacl_property_class_constraint_modes(tmp_path):
    """
    In default mode, property shapes with a class range emit sh:class <class_uri>.
    In native names mode, property shapes with a class range emit sh:node <native_shape_uri>.

    This tests the fix for the bug where --use-native-names incorrectly emitted
    sh:class <native_shape_uri> — a URI that data nodes are never typed as.
    """
    test_schema = """
id: http://example.org/test
name: range_class_test
prefixes:
  ex: http://example.org/
  linkml: https://w3id.org/linkml/
default_prefix: ex

imports:
  - linkml:types

classes:
  Target:
    description: The class used as a range
    class_uri: ex:ExternalTarget
    slots:
      - label

  Container:
    description: Has a slot whose range is Target
    slots:
      - has_target

slots:
  label:
    range: string

  has_target:
    range: Target
"""

    schema_path = tmp_path / "range_class_test.yaml"
    schema_path.write_text(test_schema)

    EX = "http://example.org/"
    CONTAINER_URI = rdflib.term.URIRef(EX + "Container")
    HAS_TARGET_URI = rdflib.term.URIRef(EX + "has_target")
    EXTERNAL_TARGET_URI = rdflib.term.URIRef(EX + "ExternalTarget")
    NATIVE_TARGET_URI = rdflib.term.URIRef(EX + "Target")

    def get_has_target_prop_node(g, container_uri):
        for prop in g.objects(container_uri, SH.property):
            paths = list(g.objects(prop, SH.path))
            if HAS_TARGET_URI in paths:
                return prop
        return None

    # --- Default mode: sh:class should use the class_uri (ExternalTarget) ---
    g_default = rdflib.Graph()
    g_default.parse(
        data=ShaclGenerator(str(schema_path), mergeimports=True, use_class_uri_names=True).serialize(),
        format="turtle",
    )
    prop_node = get_has_target_prop_node(g_default, CONTAINER_URI)
    assert prop_node is not None, "Container shape missing has_target property"

    class_objects = list(g_default.objects(prop_node, SH["class"]))
    node_objects = list(g_default.objects(prop_node, SH["node"]))

    assert EXTERNAL_TARGET_URI in class_objects, (
        f"Default mode: expected sh:class ex:ExternalTarget (class_uri), got {class_objects}"
    )
    assert node_objects == [], f"Default mode: sh:node must not be emitted, got {node_objects}"

    # --- Native names mode: sh:node should use the LinkML class name (Target) ---
    g_native = rdflib.Graph()
    g_native.parse(
        data=ShaclGenerator(str(schema_path), mergeimports=True, use_class_uri_names=False).serialize(),
        format="turtle",
    )
    prop_node_native = get_has_target_prop_node(g_native, CONTAINER_URI)
    assert prop_node_native is not None, "Container shape missing has_target property in native mode"

    class_objects_native = list(g_native.objects(prop_node_native, SH["class"]))
    node_objects_native = list(g_native.objects(prop_node_native, SH["node"]))

    assert NATIVE_TARGET_URI in node_objects_native, (
        f"Native mode: expected sh:node ex:Target (native shape name), got {node_objects_native}"
    )
    assert class_objects_native == [], (
        f"Native mode: sh:class must not be emitted (was the old bug), got {class_objects_native}"
    )
    # Also verify the wrong value (the old bug) is absent
    assert EXTERNAL_TARGET_URI not in node_objects_native, (
        "Native mode: sh:node must not use the class_uri (ExternalTarget)"
    )


# ---------------------------------------------------------------------------
# 3. sh:node must reference a shape that was actually emitted, including --suffix
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("suffix", [None, "Shape"])
def test_shacl_native_node_reference_resolves(tmp_path, suffix):
    """
    In native names mode, sh:node points at a shape identifier rather than an RDF
    class, so it must match the emitted shape name exactly — including any string
    appended via the ``suffix`` option.  A reference to a shape that does not exist
    is not an error in SHACL: the constraint simply passes everything, silently
    dropping the validation the user asked for.
    """
    test_schema = """
id: http://example.org/test
name: suffix_range_test
prefixes:
  ex: http://example.org/
  linkml: https://w3id.org/linkml/
default_prefix: ex

imports:
  - linkml:types

classes:
  Target:
    class_uri: ex:ExternalTarget
    slots:
      - label

  Container:
    slots:
      - has_target

slots:
  label:
    range: string

  has_target:
    range: Target
"""
    schema_path = tmp_path / "suffix_range_test.yaml"
    schema_path.write_text(test_schema)

    expected = rdflib.term.URIRef("http://example.org/Target" + (suffix or ""))

    g = rdflib.Graph()
    g.parse(
        data=ShaclGenerator(str(schema_path), mergeimports=True, use_class_uri_names=False, suffix=suffix).serialize(),
        format="turtle",
    )

    node_objects = set(g.objects(None, SH["node"]))
    assert node_objects == {expected}, f"Expected sh:node {expected}, got {node_objects}"

    emitted_shapes = set(g.subjects(RDF.type, SH.NodeShape))
    assert node_objects <= emitted_shapes, (
        f"sh:node references a shape that was never emitted: {node_objects - emitted_shapes}"
    )


# ---------------------------------------------------------------------------
# 4. INLINED VALUES: sh:node <range shape> with inlined_as_node
# ---------------------------------------------------------------------------
INLINED_SCHEMA = """
id: http://example.org/test
name: inlined_test
prefixes:
  ex: http://example.org/
  linkml: https://w3id.org/linkml/
default_prefix: ex

imports:
  - linkml:types

classes:
  Category:
    description: Has an identifier, so a non-inlined value is a reference
    slots:
      - id

  Link:
    class_uri: ex:ExternalLink
    slots:
      - label
      - category
    slot_usage:
      label:
        required: true

  Note:
    description: Has no identifier, so it can only be inlined
    slots:
      - label

  Container:
    slots:
      - link
      - note
      - choice
      - mixed
      - derived_link

slots:
  id:
    identifier: true
    range: uriorcurie
  label:
    range: string
  category:
    range: Category
  link:
    range: Link
    inlined: true
  note:
    range: Note
  choice:
    any_of:
      - range: Link
      - range: Note
    inlined: true
  mixed:
    any_of:
      - range: Category
      - range: Note
  derived_link:
    is_a: link
"""

EX = "http://example.org/"


def _constraints(g, shape, path):
    """The sh:class / sh:node values of the property shape for *path*, plus those of its sh:or members."""
    found = {"class": set(), "node": set()}
    for prop in g.objects(rdflib.URIRef(shape), SH.property):
        if rdflib.URIRef(EX + path) not in set(g.objects(prop, SH.path)):
            continue
        members = [prop]
        for or_list in g.objects(prop, SH["or"]):
            members.extend(Collection(g, or_list))
        for member in members:
            found["class"] |= {str(o) for o in g.objects(member, SH["class"])}
            found["node"] |= {str(o) for o in g.objects(member, SH["node"])}
    return found


def _shacl(tmp_path, **kwargs):
    schema_path = tmp_path / "inlined_test.yaml"
    schema_path.write_text(INLINED_SCHEMA)
    g = rdflib.Graph()
    g.parse(data=ShaclGenerator(str(schema_path), mergeimports=True, **kwargs).serialize(), format="turtle")
    return g


def test_inlined_as_node_off_keeps_sh_class(tmp_path):
    """By default an inlined class range still emits sh:class, as before."""
    g = _shacl(tmp_path)
    assert _constraints(g, EX + "Container", "link") == {"class": {EX + "ExternalLink"}, "node": set()}
    assert _constraints(g, EX + "Container", "note") == {"class": {EX + "Note"}, "node": set()}


@pytest.mark.parametrize("suffix", [None, "Shape"])
def test_inlined_as_node_inlined_range_emits_sh_node(tmp_path, suffix):
    """An inlined value is validated against the range class's shape, named after its class_uri."""
    g = _shacl(tmp_path, inlined_as_node=True, suffix=suffix)
    suffix = suffix or ""
    container = EX + "Container" + suffix

    # explicitly inlined
    assert _constraints(g, container, "link") == {"class": set(), "node": {EX + "ExternalLink" + suffix}}
    # inlined because the range class has no identifier
    assert _constraints(g, container, "note") == {"class": set(), "node": {EX + "Note" + suffix}}
    # inlined through the slot's is_a ancestor
    assert _constraints(g, container, "derived_link") == {"class": set(), "node": {EX + "ExternalLink" + suffix}}

    # every sh:node reference points at a shape that was emitted
    emitted = {str(s) for s in g.subjects(RDF.type, SH.NodeShape)}
    referenced = {str(o) for o in g.objects(None, SH["node"])}
    assert referenced <= emitted, f"sh:node references shapes that were never emitted: {referenced - emitted}"


def test_inlined_as_node_reference_keeps_sh_class(tmp_path):
    """A reference to an identified object keeps sh:class: only its type is visible from here."""
    g = _shacl(tmp_path, inlined_as_node=True)
    assert _constraints(g, EX + "ExternalLink", "category") == {"class": {EX + "Category"}, "node": set()}


def test_inlined_as_node_any_of_members(tmp_path):
    """Each any_of member is decided on its own: inlined members get sh:node, references sh:class."""
    g = _shacl(tmp_path, inlined_as_node=True)
    assert _constraints(g, EX + "Container", "choice") == {
        "class": set(),
        "node": {EX + "ExternalLink", EX + "Note"},
    }
    # not declared inlined: Category (has an identifier) is a reference, Note can only be inlined
    assert _constraints(g, EX + "Container", "mixed") == {"class": {EX + "Category"}, "node": {EX + "Note"}}


def test_inlined_as_node_native_names_unaffected(tmp_path):
    """Native names mode already emits sh:node for every class range; the option changes nothing there."""
    with_option = _shacl(tmp_path, inlined_as_node=True, use_class_uri_names=False)
    without = _shacl(tmp_path, inlined_as_node=False, use_class_uri_names=False)
    assert isomorphic(with_option, without)


def test_inlined_as_node_validates_untyped_inlined_value():
    """End-to-end: an inlined value is checked by its content, not by a stated type."""
    import pyshacl

    shacl_ttl = ShaclGenerator(INLINED_SCHEMA, mergeimports=True, inlined_as_node=True).serialize()
    prefixes = "@prefix ex: <http://example.org/> .\n"

    # untyped inlined link with its required label: conforms
    conforms, _, text = pyshacl.validate(
        data_graph=prefixes + 'ex:c a ex:Container ; ex:link [ ex:label "x" ; ex:category ex:cat ] .\n'
        "ex:cat a ex:Category .",
        shacl_graph=shacl_ttl,
        data_graph_format="turtle",
        shacl_graph_format="turtle",
    )
    assert conforms, text

    # untyped inlined link without its required label: rejected by the Link shape
    conforms, _, text = pyshacl.validate(
        data_graph=prefixes + "ex:c a ex:Container ; ex:link [ ex:category ex:cat ] .\nex:cat a ex:Category .",
        shacl_graph=shacl_ttl,
        data_graph_format="turtle",
        shacl_graph_format="turtle",
    )
    assert not conforms
    assert "MinCountConstraintComponent" in text, text

    # a reference still has to be typed
    conforms, _, text = pyshacl.validate(
        data_graph=prefixes + 'ex:c a ex:Container ; ex:link [ ex:label "x" ; ex:category ex:untyped ] .',
        shacl_graph=shacl_ttl,
        data_graph_format="turtle",
        shacl_graph_format="turtle",
    )
    assert not conforms
    assert "ClassConstraintComponent" in text, text


def test_inlined_as_node_class_expression_condition_range(tmp_path):
    """A slot condition's range follows its slot; the is_a of a class expression stays a type test."""
    narrowed = """
  Narrowed:
    is_a: Container
    any_of:
      - is_a: Container
        slot_conditions:
          link:
            range: Link

slots:
  id:"""
    schema = INLINED_SCHEMA.replace("\nslots:\n  id:", narrowed, 1)
    schema_path = tmp_path / "inlined_condition.yaml"
    schema_path.write_text(schema)
    g = rdflib.Graph()
    g.parse(
        data=ShaclGenerator(str(schema_path), mergeimports=True, inlined_as_node=True).serialize(),
        format="turtle",
    )
    (member,) = Collection(g, g.value(rdflib.URIRef(EX + "Narrowed"), SH["or"]))
    assert g.value(member, SH["class"]) == rdflib.URIRef(EX + "Container")
    condition = g.value(member, SH.property)
    assert g.value(condition, SH.path) == rdflib.URIRef(EX + "link")
    assert g.value(condition, SH["node"]) == rdflib.URIRef(EX + "ExternalLink")
    assert g.value(condition, SH["class"]) is None


_INHERITANCE_SCHEMA = """
id: http://example.org/test
name: inheritance_test
prefixes:
  ex: http://example.org/
  linkml: https://w3id.org/linkml/
default_prefix: ex
imports:
  - linkml:types
classes:
  Artifact:
    class_uri: ex:Artifact
    slots: [code, name]
    any_of:
      - slot_conditions:
          code: {required: true}
      - slot_conditions:
          name: {required: true}
  Named:
    mixin: true
    slots: [name]
  Report:
    class_uri: ex:Report
    is_a: Artifact
    mixins: [Named]
  Holder:
    slots: [report]
slots:
  code: {}
  name: {}
  report:
    range: Report
    inlined: true
"""


@pytest.mark.parametrize("inlined_as_node", [False, True])
def test_inlined_as_node_class_shape_conforms_to_its_parents(inlined_as_node):
    """With the option, a class shape requires its is_a parent's and mixins' shapes."""
    g = rdflib.Graph()
    g.parse(data=ShaclGenerator(_INHERITANCE_SCHEMA, inlined_as_node=inlined_as_node).serialize(), format="turtle")
    parents = set(g.objects(rdflib.URIRef(EX + "Report"), SH["node"]))
    expected = {rdflib.URIRef(EX + "Artifact"), rdflib.URIRef(EX + "Named")} if inlined_as_node else set()
    assert parents == expected


def test_inlined_as_node_applies_inherited_class_expressions():
    """An untyped inlined value is held to the class expressions of its range class's ancestors."""
    import pyshacl

    shacl_ttl = ShaclGenerator(_INHERITANCE_SCHEMA, inlined_as_node=True).serialize()
    prefixes = "@prefix ex: <http://example.org/> .\n"
    for report, expected in (('[ ex:code "c1" ]', True), ("[ ex:other 1 ]", False)):
        conforms, _, text = pyshacl.validate(
            data_graph=prefixes + f"ex:h a ex:Holder ; ex:report {report} .",
            shacl_graph=shacl_ttl,
            data_graph_format="turtle",
            shacl_graph_format="turtle",
        )
        assert conforms is expected, text


def test_inlined_as_node_native_names_parents_unaffected():
    with_option = rdflib.Graph().parse(
        data=ShaclGenerator(_INHERITANCE_SCHEMA, inlined_as_node=True, use_class_uri_names=False).serialize(),
        format="turtle",
    )
    without = rdflib.Graph().parse(
        data=ShaclGenerator(_INHERITANCE_SCHEMA, use_class_uri_names=False).serialize(), format="turtle"
    )
    assert isomorphic(with_option, without)
