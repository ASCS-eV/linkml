JSON-LD Contexts
================

.. note ::
    When run with ``--emit-frame``, the generator writes a ``.frame.jsonld`` with ``@embed`` directives
    derived from slot ``inlined`` settings (``@always`` / ``@never``).

    Example::

        gen-jsonld-context schema.yaml --output schema.context.jsonld --emit-frame

    This produces two files:

    * ``schema.context.jsonld`` – the JSON-LD context
    * ``schema.frame.jsonld`` – the JSON-LD frame (only if @embed rules are present)

    Alternatively, you can embed the context directly into the frame and produce a single file::

        gen-jsonld-context schema.yaml --output schema.jsonld --embed-context-in-frame

    This produces one file:

    * ``schema.frame.jsonld`` – the JSON-LD frame with the full ``@context`` embedded

    ``--emit-frame`` and ``--embed-context-in-frame`` require ``--output``.

.. warning ::

    The JSON-LD context generator does not yet include ``@type``
    directives except at the top level.

Overview
--------

`JSON-LD context <https://www.w3.org/TR/json-ld/#the-context>`__
provides mapping from JSON to RDF.

.. code:: bash

   gen-jsonld-context personinfo.yaml > personinfo.context.jsonld

You can control the output via
`prefixes <https://linkml.io/linkml-model/latest/docs/prefixes/>`__
declarations and
`default_curi_maps <https://linkml.io/linkml-model/latest/docs/default_curi_maps/>`__.

Any JSON that conforms to the derived JSON Schema (see above) can be
converted to RDF using this context.

Treatment of OBO prefixes
-------------------------

All OBO ontologies use prefixes that end in underscores (for example
``http://purl.obolibrary.org/obo/PATO_``). Note that the JSON-LD 1.1
spec doesn't allow trailing underscores on simple "flat" prefix maps,
i.e this is not correct:

.. code:: json

   "@context": {
       "PATO": "http://purl.obolibrary.org/obo/PATO_",
        }

It must be represented as:

.. code:: json

   "@context": {
       "PATO": {
            "@id": "http://purl.obolibrary.org/obo/PATO_",
             "@prefix": true
        }

However, the former can still be convenient, so this can be done with
a flag:

.. code:: bash

   gen-jsonld-context --flatprefixes personinfo.yaml > personinfo.context.jsonld

However, this is not recommended and newer applications should switch
to gen-prefix-map:

.. code:: bash

   gen-prefix-map --flatprefixes personinfo.yaml > personinfo.prefixmap.json

URIs as IRIs or as literals
---------------------------

By default a ``uri`` or ``uriorcurie`` slot is coerced to ``xsd:anyURI``, a typed
literal. ``--xsd-anyuri-as-iri`` coerces it to ``@id`` instead, so the value becomes an
IRI node, matching the ``sh:nodeKind sh:IRI`` the SHACL generator emits. The OWL
generator accepts the same flag.

The flag applies to ``uri``, ``uriorcurie`` and their derived types when the
effective datatype remains ``xsd:anyURI``. Datatype IRIs are expanded before
comparison, so full IRIs and alternative prefixes behave identically. A type
derived from ``string`` that declares ``uri: xsd:anyURI`` stays a typed literal with or
without it. Use one for a URI reference that is data rather than a link, such as a file
path that may be relative: as ``@id`` it would be resolved against the document base.

.. code-block:: yaml

    types:
      FilePath:
        typeof: string
        uri: xsd:anyURI     # always "@type": "xsd:anyURI", sh:datatype xsd:anyURI
    slots:
      homepage:
        range: uri          # "@id" with --xsd-anyuri-as-iri
      file_path:
        range: FilePath

The RDF dumper, SHACL and ShEx generators distinguish the same URI family from
literal-valued types. An explicit datatype override such as ``uri: xsd:string``
remains literal-valued, including when the type inherits from ``uri``.

`XSD anyURI <https://www.w3.org/TR/xmlschema11-2/#anyURI>`__ admits relative URI
references as literal values. This differs from an RDF IRI node: `JSON-LD type
coercion <https://www.w3.org/TR/json-ld11/#type-coercion>`__ with ``@id`` interprets
strings as identifiers and resolves relative references against the base IRI.
The existing option selects the JSON-LD/OWL representation of LinkML's URI
family; it is not needed to preserve a deliberately literal-valued type. No
additional option is introduced.


Docs
----

Command Line
^^^^^^^^^^^^

.. currentmodule:: linkml.generators.jsonldcontextgen

.. click:: linkml.generators.jsonldcontextgen:cli
    :prog: gen-jsonld-context
    :nested: short

Code
^^^^


.. autoclass:: ContextGenerator
    :members: serialize
