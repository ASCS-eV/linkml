"""RDF annotation terms governed by declared LinkML metamodel extensions."""

from typing import Any

from rdflib import XSD, BNode, Literal, URIRef

from linkml_runtime.linkml_model import Element, PermissibleValue, SlotDefinition
from linkml_runtime.linkml_model.types import SHEX
from linkml_runtime.utils.schemaview import SchemaView
from linkml_runtime.utils.uri_validator import validate_uri


def declared_annotation(
    schema: SchemaView,
    element: Element | PermissibleValue,
    tag: str,
    value: Any,
    language: str | None = None,
) -> tuple[URIRef, URIRef | BNode | Literal] | None:
    """Serialize a scalar annotation using an instantiated metaclass's slot.

    Match local slot names or expanded slot URIs in the induced metaclass,
    including inherited and imported definitions. Unresolved external metaclasses
    and undeclared tags leave the caller's existing behavior unchanged. Conflicting
    declarations fail instead of selecting a range according to iteration order.

    This is RDF serialization, not annotation constraint validation. The
    metamodel-extension contract is described in LinkML specification section 5,
    ``Metamodel refinement using annotations``.
    """
    declarations: list[SlotDefinition] = []
    for metaclass in element.instantiates:
        identifier = schema.expand_curie(metaclass)
        for cls in schema.all_classes().values():
            if schema.get_uri(cls, expand=True) != identifier:
                continue
            for slot in schema.class_induced_slots(cls.name):
                if tag == slot.name or schema.expand_curie(tag) == schema.get_uri(slot, expand=True):
                    declarations.append(slot)
    if not declarations:
        return None
    terms = {
        (URIRef(schema.get_uri(slot, expand=True)), _annotation_value(schema, slot, value, language))
        for slot in declarations
    }
    if len(terms) != 1:
        raise ValueError(f"Conflicting metaclass declarations for annotation {tag!r}")
    return terms.pop()


def _annotation_value(
    schema: SchemaView, slot: SlotDefinition, value: Any, language: str | None
) -> URIRef | BNode | Literal:
    """Convert a declared scalar range to its RDF term without vocabulary guessing."""
    if slot.any_of or slot.all_of or slot.exactly_one_of or slot.none_of or slot.range_expression:
        raise ValueError(f"Annotation {slot.name!r} requires a single scalar range for RDF serialization")
    if not isinstance(value, str | bool | int | float):
        raise ValueError(f"Annotation {slot.name!r} requires a scalar RDF value")
    if slot.range not in schema.all_types():
        raise ValueError(f"Annotation {slot.name!r} has unsupported non-scalar range {slot.range!r}")
    typ = schema.induced_type(slot.range)
    datatype = URIRef(schema.expand_curie(typ.uri)) if typ.uri else None
    # The standard curie type requires expansion in RDF even though its lexical
    # datatype is xsd:string. nodeidentifier explicitly denotes a non-literal;
    # xsd:anyURI alone does not distinguish an IRI node from a URI literal.
    curie = datatype == XSD.string and "curie" in schema.type_ancestors(slot.range)
    if datatype in (SHEX.iri, SHEX.nonLiteral) or curie:
        if not isinstance(value, str):
            raise ValueError(f"Annotation {slot.name!r} requires a node identifier")
        if datatype == SHEX.nonLiteral and value.startswith("_:") and len(value) > 2:
            return BNode(value[2:])
        expanded = schema.expand_curie(value)
        if not validate_uri(expanded):
            raise ValueError(f"Annotation {slot.name!r} requires an absolute IRI or declared CURIE: {value!r}")
        return URIRef(expanded)
    if datatype in (None, XSD.string):
        return Literal(value, lang=language if isinstance(value, str) else None)
    return Literal(value, datatype=datatype)
