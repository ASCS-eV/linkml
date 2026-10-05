SHACL
======

.. warning:: Beta implementation, some features may change

Example Output
--------------

`personinfo.shacl.ttl <https://github.com/linkml/linkml/tree/main/examples/PersonSchema/personinfo/shacl/personinfo.shacl.ttl>`_

Overview
--------

`SHACL <https://www.w3.org/TR/shacl/>`__ (Shapes Constraint Language) is a language for validating RDF graphs against a set of conditions

To run:

.. code:: bash

   gen-shacl personinfo.yaml > personinfo.shacl.ttl



Docs
----

Example Input:

.. code-block:: yaml

  NamedThing:
    slots:
      - id
      - name

  HasAliases:
    mixin: true
    attributes:
      aliases:
        multivalued: true

  Person:
    is_a: NamedThing
    mixins:
      - HasAliases
    slots:
      - birth_date
      - age_in_years
      - gender

Example Output:

.. code-block:: turtle

    <https://w3id.org/linkml/tests/kitchen_sink/Person> a shacl:NodeShape ;
        shacl:closed true ;
        shacl:ignoredProperties ( rdf:type ) ;
        shacl:property [ shacl:class <https://w3id.org/linkml/tests/kitchen_sink/BirthEvent> ;
                shacl:maxCount 1 ;
                shacl:nodeKind shacl:BlankNode ;
                shacl:path <https://w3id.org/linkml/tests/kitchen_sink/has_birth_event> ],
            [ shacl:maxCount 1 ;
                shacl:maxInclusive 999 ;
                shacl:minInclusive 0 ;
                shacl:path <https://w3id.org/linkml/tests/kitchen_sink/age_in_years> ],
            [ shacl:class <https://w3id.org/linkml/tests/kitchen_sink/FamilialRelationship> ;
                shacl:nodeKind shacl:BlankNode ;
                shacl:path <https://w3id.org/linkml/tests/kitchen_sink/has_familial_relationships> ],
            [ shacl:maxCount 1 ;
                shacl:path <https://w3id.org/linkml/tests/core/name> ;
                shacl:pattern "^\\S+ \\S+" ],
            [ shacl:class <https://w3id.org/linkml/tests/kitchen_sink/MedicalEvent> ;
                shacl:nodeKind shacl:BlankNode ;
                shacl:path <https://w3id.org/linkml/tests/kitchen_sink/has_medical_history> ],
            [ shacl:class <https://w3id.org/linkml/tests/kitchen_sink/Address> ;
                shacl:nodeKind shacl:BlankNode ;
                shacl:path <https://w3id.org/linkml/tests/kitchen_sink/addresses> ],
            [ shacl:maxCount 1 ;
                shacl:path <https://w3id.org/linkml/tests/core/id> ],
            [ shacl:path <https://w3id.org/linkml/tests/kitchen_sink/aliases> ],
            [ shacl:class <https://w3id.org/linkml/tests/kitchen_sink/EmploymentEvent> ;
                shacl:nodeKind shacl:BlankNode ;
                shacl:path <https://w3id.org/linkml/tests/kitchen_sink/has_employment_history> ] ;
        shacl:targetClass <https://w3id.org/linkml/tests/kitchen_sink/Person> .


Rule constraints (SHACL-SPARQL)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

LinkML `rules <https://w3id.org/linkml/rules>`_ state conditional
constraints ("if slot A holds X, slot B must ..."), which property shapes
cannot express. The generator translates each rule into a
`SHACL-SPARQL constraint <https://www.w3.org/TR/shacl/#sparql-constraints>`_
(``sh:sparql``) on the node shape of its class, and of every subclass, since
a rule applies to all members of its class. ``--no-emit-rules`` turns this
off.

The constraint's query selects each focus node that satisfies the
preconditions and violates the postconditions. ``$this`` is the focus node
(`SHACL §5.3.1 <https://www.w3.org/TR/shacl/#sparql-constraints-prebound>`_),
and each result names the postcondition's property and, where there is one,
the offending value (``sh:resultPath``, ``sh:value``).

Two patterns are recognised first:

* **Presence implies value**: precondition ``value_presence: PRESENT`` on a
  guard slot, and postcondition ``equals_string`` or ``equals_string_in`` on a
  target slot.
* **Exclusive value**: precondition ``has_member: {equals_string: V}``, and
  postcondition ``maximum_cardinality`` on the same slot. The older form
  with a bare ``equals_string: V`` precondition is read the same way, with a
  warning.

Any other rule with one postcondition slot is composed from the operators
its conditions use: ``value_presence``, ``required``, ``equals_string``,
``equals_string_in``, ``minimum_value``, ``maximum_value``,
``range_expression`` (slot conditions on the slot's class) and
``has_member``.

All translations follow the JSON Schema generator's ``if`` / ``then``:

* **Presence:** ``value_presence`` decides, then ``required``. Otherwise a
  precondition requires its slot, a postcondition requires its slot unless
  the rule is ``open_world``, and a condition inside a ``range_expression``
  or ``has_member`` does not.
* **Multivalued slots:** a condition holds when *every* value satisfies it.
  ``has_member`` holds when *some* value does.
* **Values:** ``equals_string`` and ``equals_string_in`` are compared as
  strings on enum and ``xsd:string`` slots, where an enum value with a
  ``meaning`` is compared as that IRI. On ``xsd:boolean`` slots they are
  compared as booleans and must be ``true``, ``false``, ``1`` or ``0``.
  ``minimum_value`` and ``maximum_value`` are inclusive bounds, translated
  only on slots whose datatype SPARQL compares as a number (``xsd:integer``,
  ``decimal``, ``float``, ``double`` and the types derived from them).

A rule outside these forms is skipped with a warning that names the rule and
the reason. It is never partially translated. ``deactivated`` rules are
ignored and ``bidirectional`` rules are skipped. For a rule with
``elseconditions``, only the if/then direction is emitted, and a warning
says so.

Example:

.. code-block:: yaml

    classes:
      Document:
        attributes:
          review_score:
            range: integer
          status:
            range: Status   # an enum: draft, approved, published
        rules:
          - description: A document scoring 4 or more must be approved or published.
            preconditions:
              slot_conditions:
                review_score:
                  minimum_value: 4
            postconditions:
              slot_conditions:
                status:
                  equals_string_in: [approved, published]

generates (abridged):

.. code-block:: turtle

    ex:Document a sh:NodeShape ;
        sh:sparql [ a sh:SPARQLConstraint ;
            sh:message "A document scoring 4 or more must be approved or published." ;
            sh:select """SELECT DISTINCT $this (<https://example.org/status> AS ?path) ?value WHERE {
        FILTER EXISTS { $this <https://example.org/review_score> ?pre0 . }
        FILTER NOT EXISTS { $this <https://example.org/review_score> ?pre0 . FILTER ( !( COALESCE( isNumeric( ?pre0 ) && ?pre0 >= 4, false ) ) ) }
        { FILTER NOT EXISTS { $this <https://example.org/status> ?value . } }
        UNION { $this <https://example.org/status> ?value . FILTER ( !( COALESCE( ?value = "approved" || ?value = "published", false ) ) ) }
    }""" ] .

A ``Document`` with a ``review_score`` of 4 or more violates the constraint
if it has no ``status``, or once for each ``status`` other than ``approved``
or ``published``, which the result reports as ``sh:value``. SHACL processors
that support SHACL-SPARQL, such as ``pyshacl``, validate these constraints.


Class Expressions
^^^^^^^^^^^^^^^^^

Class-level boolean expressions become the SHACL logical constraint components
their metamodel definitions map to (`SHACL §4.6
<https://www.w3.org/TR/shacl/#core-components-logical>`__):

==================  =====================================================
LinkML              SHACL, on the class's ``sh:NodeShape``
==================  =====================================================
``any_of``          ``sh:or`` over the member shapes
``all_of``          ``sh:and`` over the member shapes
``exactly_one_of``  ``sh:xone`` over the member shapes
``none_of``         one ``sh:not`` per member
==================  =====================================================

Each member becomes an anonymous node shape. ``is_a`` gives ``sh:class`` for a
class and the value constraint of a type or an enum otherwise, and nested
expressions recurse. Each entry of ``slot_conditions`` gives an
``sh:property`` whose path is that of the slot as induced for the class, so
``slot_usage`` applies:

* ``required``, ``value_presence`` and the cardinalities give ``sh:minCount`` /
  ``sh:maxCount``;
* ``minimum_value`` / ``maximum_value`` give ``sh:minInclusive`` /
  ``sh:maxInclusive``, and ``equals_number`` gives both, so that ``5`` also
  matches ``5.0``;
* ``pattern`` gives ``sh:pattern``;
* ``equals_string`` and ``equals_string_in`` give ``sh:in``; on an enum slot the
  values are the permissible values as the enum renders them, the IRI of their
  ``meaning`` where they have one;
* ``range`` gives the same class, type or enum constraint as a slot's range;
* ``range_expression`` gives an ``sh:node``, as described under
  `Range Expressions`_.

A shape may have at most one value of ``sh:minInclusive``, ``sh:maxInclusive``
or ``sh:in``, and of ``sh:pattern``, whose component also takes ``sh:flags``
(`SHACL §2.1.1 <https://www.w3.org/TR/shacl/#constraints>`__). Where one condition
needs one of them twice, for example ``minimum_value`` next to
``equals_number``, the second value goes into an ``sh:and`` member of the
property shape, where it applies to the same values.

A slot condition is unknown for an absent slot unless it decides whether the slot
may be absent, and an instance violates an expression only when the expression is
definitely false, as described under "Class-level expressions and absent slots" in
:doc:`Advanced features </schemas/advanced>`.
The JSON Schema generator reads them the same way. In SHACL, each expression gets
its "not false" form, and, under ``sh:not``, its "definitely true" form, where
such a condition also requires its slot (``sh:minCount 1``). ``exactly_one_of``
becomes ``sh:xone`` over the "definitely true" forms of its members.

.. code-block:: yaml

  GeodeticReferenceSystem:
    slots: [code, name]
    any_of:
      - slot_conditions:
          code:
            required: true
      - slot_conditions:
          name:
            required: true

.. code-block:: turtle

    ex:GeodeticReferenceSystem a sh:NodeShape ;
        sh:or ( [ sh:property [ sh:path ex:code ; sh:minCount 1 ] ]
                [ sh:property [ sh:path ex:name ; sh:minCount 1 ] ] ) ;
        ...

A class expression constrains every instance of its class, so the shape of a
class carries the expressions of its ancestors and mixins as well, as it carries
their slots. Each is translated in the context of that class, where
``slot_usage`` applies. A node typed only with a subclass, as ``rdflib_dumper``
and the JSON-LD context produce it, is therefore checked without an
``rdfs:subClassOf`` triple in the data. The ``sh:class`` that ``is_a`` gives
recognises instances of subclasses only where the data graph states the
``rdfs:subClassOf`` (`SHACL §4.1.1
<https://www.w3.org/TR/shacl/#ClassConstraintComponent>`__), as it does for a
slot's range.

An operator whose members use anything else is skipped as a whole and logged as
a warning, because leaving out one member would change what the operator
admits. That covers, for example, ``has_member``, ``equals_expression`` or a
slot-level ``any_of`` inside a slot condition, a condition on a name that is not a slot, a condition
on the identifier slot (the node's IRI rather than a property), and
``equals_string`` on a slot whose range does not hold strings.


Range Expressions
^^^^^^^^^^^^^^^^^

A slot's `range_expression <https://w3id.org/linkml/range_expression>`__
constrains each of its values as a class-level expression constrains an
instance: its conditions constrain the slots of the value as induced for the
range class, and a value violates it only when it is definitely false. It
becomes an ``sh:node`` (`SHACL §4.7.1
<https://www.w3.org/TR/shacl/#NodeConstraintComponent>`__) on the property shape,
next to the range's ``sh:class``, so it constrains only the values of this slot,
and matching it doesn't make a node an instance of the range. The JSON Schema
generator reads it the same way.

.. code-block:: yaml

   classes:
     Document:
       slots: [license]
       slot_usage:
         license:
           range_expression:
             slot_conditions:
               category:
                 required: true
                 equals_string: license
     Resource:
       slots: [category]
   slots:
     license:
       range: Resource
     category:
       range: string

.. code-block:: turtle

   ex:Document a sh:NodeShape ;
       sh:property [ sh:path ex:license ;
               sh:class ex:Resource ;
               sh:node [ sh:property [ sh:path ex:category ;
                           sh:minCount 1 ;
                           sh:in ( "license" ) ] ] ;
               ... ] ;
       ...

A class alternative in a slot's ``any_of`` can carry its own
``range_expression``, and so can a slot condition, where the expression takes
the form of the condition: under ``sh:not``, its "definitely true" form. For
values that aren't instances of a class, an expression can combine types and
enums with ``is_a``, for example ``any_of: [{is_a: OpenLicense}, {is_a:
ProprietaryLicense}]``; such values have no slots for a condition to constrain.
An expression that uses anything SHACL can't express (see above) is skipped and
logged as a warning.

A value that is a reference is checked against its description in the data
graph, as ``sh:class`` is. The JSON Schema generator can't check it, because
there the value is just an identifier.


Command Line
^^^^^^^^^^^^

.. currentmodule:: linkml.generators.shaclgen

.. click:: linkml.generators.shaclgen:cli
    :prog: gen-shacl
    :nested: short

Code
^^^^


.. autoclass:: ShaclGenerator
    :members: serialize
