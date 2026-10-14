OWL
===

Example Output
--------------

`personinfo.owl.ttl <https://github.com/linkml/linkml/tree/main/examples/PersonSchema/personinfo/owl/personinfo.owl.ttl>`_

Overview
--------

Web Ontology Language
`OWL <https://www.w3.org/TR/2012/REC-owl2-overview-20121211/>`_ is a
modeling language used to author ontologies.

OWL is used for building *ontologies*, whereas LinkML is a *schema*
language. Nevertheless, it can be useful to render Schemas as OWL (and
in fact many semantic web schemas such as PROV have an OWL or RDFS
rendering)


.. seealso:: The `linkml-owl <https://github.com/linkml/linkml-owl>`_
             maps between LinkML *data* and OWL

.. note:: The OWL is rendered as RDF/turtle. We recommend the suffix
          ``.owl.ttl`` to distinguish from the direct RDF mapping


Mapping
^^^^^^^

* Each LinkML class maps to an OWL class
* Each LinkML slot maps to an OWL property

    - if the range of the slot is class, then an ObjectProperty is used
    - otherwise DataProperty is used
    - Exception to the above: if ``type_objects`` is set then ObjectProperties are always used;
      instead of having ranges of type be mapped to literals, these map to class-shadows of
      literals, that have a data property ``value``.
      This can be useful in some scenarios - for example, if you want to use the same property and
      allow *either* literals or objects as values.

* OWL *restrictions* are used for cardinality and range constraints

    - ``only`` (universal restrictions) is used for ranges
    - If a slot is not `multivalued` then ``max 1`` cardinality
      restrictions are used
    - required non-multivalued slots have an ``exactly 1`` cardinality restriction
    - required slots have a ``min 1`` cardinality restriction
    - non-required slots have a ``min 0`` cardinality restriction. Note that formally
      this is tautological and not necessary. However, adding this axiom helps make the intention
      explicit.
    - it should be understood that OWL follows the Open World
      Assumption, thus OWL reasoners enforce a weaker model

* By default both ``is_a`` and ``mixins`` are mapped to ``rdfs:subClassOf``

    - Use ``--mixins-as-expressions`` to treat mixins as existential axioms

* Each LinkML element is rendered as an instance of the relevant metamodel class

    - This means *punning* is used
    - Set ``--no-metaclasses`` if you do not want this behavior
    - Set ``--add-root-classes`` to add a root class for each metamodel class



.. note:: The current default settings for ``metaclasses`` and ``type-objects`` may change in the future

Declared annotation values
^^^^^^^^^^^^^^^^^^^^^^^^^^

An annotation property name does not determine whether its value is a literal
or an RDF node. For example, ``rdfs:Resource`` includes literals, and OWL permits
both IRIs and literals as annotation values. The generator does not maintain a
list of vocabulary properties whose string values should be changed into IRIs.

Use LinkML's metamodel extension mechanism to declare the distinction. An
``instantiates`` reference identifies a metaclass whose slots describe the
annotations on that schema element. ``nodeidentifier`` denotes an IRI, CURIE or
blank node; ``string`` denotes text, even when the text looks like a URL.
Independently, ``implements: [owl:AnnotationProperty]`` selects the existing
OWL annotation-property projection for a slot:

.. literalinclude:: ../examples/owl-annotation-properties.yaml
    :language: yaml

The ontology has ``ex:reference <https://example.org/target>`` and
``ex:text "https://example.org/a-textual-label"``, with both predicates declared
as annotation properties. The same mechanism
works for custom properties and annotations on classes, slots, local types,
enums and non-literal permissible values. Metaclass inheritance and imported
metaclasses are supported. Tags may be slot names, CURIEs or full slot IRIs.
Class inheritance, mixins and slot usage use effective slot declarations.
``implements`` itself is not inherited through a global slot's ``is_a``;
declare the annotation-property role on both members of a global subproperty
relationship.
OWL's nine built-in annotation-property IRIs, including ``rdfs:label``,
``owl:priorVersion`` and ``owl:versionInfo``, have their specification-defined
role automatically when used as actual output predicate IRIs. An explicit
object/datatype role on those IRIs is rejected. With native URIs, a locally
named property mapped to a built-in can still be an ordinary logical property;
the local output IRI determines its role.
Declared annotations accept full predicate IRIs. Undeclared tags retain the
existing CURIE/name fallback; URL-looking values are never promoted to nodes.

``instantiates`` supplies metadata declarations; it does not automatically
convert every slot of a metadata class to an OWL annotation property. The
generator declares predicates used for annotations and rejects collisions
between annotation and logical property roles, and contradictory explicit
roles at the same output IRI, including available imported definitions.
Existing inferred object/datatype range ambiguities are outside this correction.
Undeclared LinkML annotations and native metadata on already logical schema predicates retain
their existing RDF metadata projection and literal values; they do not request
an OWL annotation-property role. Declared metaclass annotations and explicit
annotation-property mappings still reject logical-role collisions. This
compatibility behavior does not establish OWL 2 DL conformance for legacy RDF.
The native-URI option still selects
local property IRIs; mapped annotation predicates can have different IRIs.

Annotation properties have no OWL logical constraint semantics. Ordinary
LinkML range, requiredness, cardinality and value constraints on these slots
remain available to instance validators, but their OWL annotation projection
omits logical restrictions. LinkML ``identifier`` and singular ``key`` flags
remain available for identity, inlining and requiredness in other consumers;
they do not request an OWL ``hasKey`` axiom. This projection does not enforce
their uniqueness in OWL. Explicit logical uses such as class ``unique_keys``, inverses,
property characteristics, type designators and rule conditions raise an error.
Global annotation properties support subproperties and simple named-IRI
domain/range axioms; those axioms do not validate annotation values. Anonymous
global annotation-property ranges are unsupported. Reserved structural
predicates such as ``owl:imports`` and ``owl:versionIRI`` cannot be supplied
as annotations; they are distinct from annotation properties.

The example above is also executed by the tests. With ``metaclasses=False``
and either value of ``type_objects`` and ``use_native_uris``, OWLAPI 5.5.0
loads, saves and reloads it with zero OWL 2 DL profile violations and retains
both header annotations. This does not establish DL conformance for every
schema or for the API's default metaclass projection.
Custom ``typeof``-only datatype aliases can also expose an existing singleton
datatype-expression profile defect. The non-header consumer fixture uses an
explicit datatype URI to test type annotations independently of that limitation.

The SHACL generator uses the same conversion when its existing
``--include-annotations`` option is enabled. Those annotations describe shapes;
they do not add constraints to ordinary data instances. Schema RDF and JSON-LD
serialization retain the LinkML annotation objects and their declarations;
they do not project annotations onto ontology properties as this generator does.

Declared scalar ranges determine term representation, as they do for slot
values: ``nodeidentifier`` allows IRIs and blank nodes, and other types produce
literals of their datatype, ``curie`` (``xsd:string``) included. An
``xsd:anyURI`` value is a literal unless ``--xsd-anyuri-as-iri`` is set, which
makes ``uri`` and ``uriorcurie`` values IRIs, as it does for slot values. Use
``nodeidentifier`` for a value that must be a node. Language tags apply to
textual literals only.

This is serialization of declared scalar annotations, not complete metamodel
extension validation. Structured values, non-type ranges and boolean range
expressions currently raise an error rather than guessing a term. Conflicting
metaclass declarations also raise an error. Unresolved external metaclasses and
undeclared tags retain each generator's existing behavior; a declaration must
be available locally or through a schema import to determine the RDF term.
Native ``contributors`` and ``license`` retain their metamodel representation;
native ``license`` remains the authoritative field. Structured agents and
export mappings for native metadata fields require separate support. Scalar
annotations do not preserve nested agent descriptions or automatically
validate all metadata extensions. Generated Python may coerce field values,
and JSON strings alone do not distinguish RDF node kinds.

The real OWLAPI consumer tests run in a dedicated CI job. To run them locally,
prepare the fixture POM's pinned dependency tree with
``maven-dependency-plugin:3.8.1:build-classpath`` and set
``LINKML_OWLAPI_CLASSPATH_FILE`` to its output file. Set
``LINKML_REQUIRE_OWLAPI=1`` to fail when that file is not configured. Ordinary
Python test runs explicitly skip only this external consumer gate when the
classpath is not configured; the dedicated job requires and executes it.

References: `LinkML metamodel refinement
<https://linkml.io/linkml-model/latest/docs/specification/05validation/>`__,
`OWL annotation values <https://www.w3.org/TR/owl2-syntax/#Annotations>`__,
`OWL property typing <https://www.w3.org/TR/owl2-syntax/#Typing_Constraints_of_OWL_2_DL>`__,
`OWL annotation axioms <https://www.w3.org/TR/owl2-syntax/#Annotation_Axioms>`__,
`OWL built-in annotation properties <https://www.w3.org/TR/owl2-syntax/#Annotation_Properties>`__,
`LinkML identifiers <https://linkml.io/linkml-model/latest/docs/identifier/>`__,
`LinkML singular keys <https://linkml.io/linkml-model/latest/docs/key/>`__,
`reserved vocabulary <https://www.w3.org/TR/owl2-syntax/#IRIs>`__,
`existing implements mapping <https://github.com/linkml/linkml/pull/2095>`__,
`RDF Schema resources <https://www.w3.org/TR/rdf-schema/#ch_resource>`__, and
`DCMI license guidance
<https://www.dublincore.org/specifications/dublin-core/dcmi-terms/#http://purl.org/dc/terms/license>`__.

Enums and PermissibleValues
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Enums and PermissibleValues provide flexible OWL representation options. By default, permissible values
are treated as *classes* and an enum has a *definition* added using an OWL ``UnionOf`` construct.

CLI Options for Controlling Enum/PV Generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``--default-permissible-value-type`` - Sets the default OWL type for permissible values

  - ``owl:Class`` (default) - PVs become OWL classes, enum uses ``owl:unionOf``
  - ``owl:NamedIndividual`` - PVs become named individuals, enum uses ``owl:oneOf``
  - ``rdfs:Literal`` - PVs become RDF literals, enum uses ``owl:oneOf``

* ``--enum-iri-separator`` - Changes the separator character in enum IRIs (default: ``#``)

Example CLI usage:

.. code-block:: bash

    # Generate enum PVs as named individuals
    gen-owl --default-permissible-value-type owl:NamedIndividual schema.yaml

    # Generate enum PVs as literals
    gen-owl --default-permissible-value-type rdfs:Literal schema.yaml

Schema Annotations for Fine-Grained Control
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can control enum and permissible value representation directly in your schema using ``implements`` annotations.

**Enum-level control** - Apply to all permissible values in an enum:

.. code-block:: yaml

    enums:
      HomePlanetType:
        implements:
         - owl:NamedIndividual
        description: The type of home planet
        permissible_values:
          Earth:
            description: Third planet from the sun
          Venus:
            description: Second planet from the sun

**Per-permissible-value control** - Override specific permissible values:

.. code-block:: yaml

    enums:
      MixedRepresentationType:
        description: Enum with mixed PV representations
        permissible_values:
          concept_term:
            description: A concept represented as a class
            implements:
              - owl:Class
          instance_value:
            description: A specific instance
            implements:
              - owl:NamedIndividual
          literal_value:
            description: A literal value
            implements:
              - rdfs:Literal

**Using URIs vs. text for permissible values:**

.. code-block:: yaml

    enums:
      StatusEnum:
        permissible_values:
          active:
            meaning: ex:ActiveStatus    # Will use URI for OWL representation
            description: Currently active
          inactive:
            description: Not active     # Will use text-based representation

OWL Output Patterns
~~~~~~~~~~~~~~~~~~~

The choice of permissible value type affects the generated OWL structure:

**owl:Class (default):**

.. code-block:: turtle

    :StatusEnum a owl:Class ;
        owl:unionOf ( :active :inactive ) .
    :active a owl:Class .
    :inactive a owl:Class .

**owl:NamedIndividual:**

.. code-block:: turtle

    :StatusEnum a owl:Class ;
        owl:oneOf ( :active :inactive ) .
    :active a owl:NamedIndividual .
    :inactive a owl:NamedIndividual .

**rdfs:Literal:**

.. code-block:: turtle

    :StatusEnum a owl:Class ;
        owl:oneOf ( "active" "inactive" ) .

Mixed Types in One Enum
~~~~~~~~~~~~~~~~~~~~~~~

When permissible values in the same enum have different ``implements`` annotations,
the behavior depends on the URI/meaning configuration:

* **All PVs have URIs**: Mixed types are supported
* **Some PVs lack URIs**: The enum may skip certain representation patterns that would be inconsistent
* **No PVs have URIs**: All PVs use the same default type

Advanced Usage
~~~~~~~~~~~~~~

**Using with different URI patterns:**

.. code-block:: yaml

    enums:
      ConceptEnum:
        permissible_values:
          term_a:
            meaning: MONDO:0001234
            implements: [owl:Class]
          term_b:
            meaning: http://example.org/TermB
            implements: [owl:NamedIndividual]


Tips
^^^^

If you wish to produce an OWL file that is primarily for browsing or release on an ontology portal
such as the Ontology Lookup Service (OLS) or OntoPortal/BioPortal, then consider using the
``--add-root-classes`` option to make the ontology more navigable.

If ``gen-owl`` is run on PersonInfo *without* this option it results in a flat structure
that is faithful and isomorphic to the existing schema:

.. code-block::

    * GenderType
    * FamilialRelationshipType
        * CHILD_OF
        * PARENT_OF
        * ...
    * Relationship
        * FamilialRelationship
    * Event
        * EmploymentEvent
        * MedicalEvent
    * NamedThing
        * Concept
    * HasAliases

Running with the option:

.. code-block::

    * EnumDefinition
        * GenderType
        * FamilialRelationshipType
    * ClassDefinition
        * Relationship
            * FamilialRelationship
        * Event
            * EmploymentEvent
            * MedicalEvent
        * NamedThing
            * Concept
        * HasAliases
    * PermissibleValue
        * CHILD_OF
        * ...

If your schema is heavy on mixins, the resulting polyhierarchy can be hard to navigate. In this case,
using ``--mixins-as-expressions`` will restrict the main subClassOf backbone to be purely ``is_a``
relationships. Mixin relationships will be modeled using existential restrictions (some values from).
OWL General Class Inclusion (GCI) axioms will be used to preserve semantics.

For example, on PersonInfo the default conversion yields:

.. code::

    Class: Person
      SubClassOf: NamedThing, HasAlias, ...
    Class: HasAlias
      SubClassOf: aliases only xsd:string, ...
    ...

Using ``--mixins-as-expressions`` gives:

.. code::

    Class: Person
      SubClassOf: NamedThing, mixins some HasAlias, ...
    Class: HasAlias
    GCIs:
      (mixins some HasAlias) SubClassOf: aliases only xsd:string, ...
    ...

Semantics of mapping from LinkML
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Generated OWL should be a faithful open-world rendering of the LinkML schema. This means that it may not be
*complete* for the purposes of data validation. If a slot is not required, then an OWL reasoner will infer
the presence of a slot value, even if not explicitly stated. However, it does not treat this as an error.

Nevertheless, it can be informative to translate schemas with rich logical information to OWL, combine these
with data converted to RDF, and then perform reasoning. If you use an ontology development environment
like Protege, this can be an intuitive way of debugging errors with your schema.

Note that currently only a subset of LinkML rules can be expressed as OWL. In future, we may
add support to generate auxhiliary SWRL files including rules.

Pitfalls
^^^^^^^^

Many OWL tools such as those based on the OWL API are intended to consume a [profile](https://www.w3.org/TR/owl2-profiles/)
of OWL called OWL-DL. It's relatively easy to create LinkML that can't be *directly* expressed in
OWL-DL, and the resulting RDF triples are said to be [OWL Full](https://www.w3.org/TR/owl2-overview/#Semantics).

For example, if you have slots in your schema that have an `Any`
range, then there is no direct translation of that slot to an OWL-DL
property, since each property needs to explicitly commit to being a
`DatatypeProperty` or `ObjectProperty` in OWL-DL.

Other examples
^^^^^^^^^^^^^^

- `Biolink <https://bioportal.bioontology.org/ontologies/BIOLINK>`_ :
  translation of Biolink schema to OWL


Docs
----

Command Line
^^^^^^^^^^^^

.. currentmodule:: linkml.generators.owlgen

.. click:: linkml.generators.owlgen:cli
    :prog: gen-owl
    :nested: short

Code
^^^^


.. autoclass:: OwlSchemaGenerator
    :members: serialize
