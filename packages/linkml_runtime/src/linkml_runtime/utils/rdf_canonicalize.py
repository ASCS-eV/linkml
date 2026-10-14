"""Deterministic RDF serialization via pyoxigraph RDFC-1.0 canonicalization.

This module provides a function to canonicalize an rdflib Graph using
pyoxigraph's RDFC-1.0 implementation, producing deterministic output
with stable blank node labels and sorted triples.

**Known limitations:**

1. **xsd:string normalization**: pyoxigraph follows RDF 1.1, where plain
   string literals and ``"text"^^xsd:string`` are identical.  The output
   will never contain explicit ``^^xsd:string`` annotations.  Code that
   re-parses the output with rdflib will see ``Literal("x")`` (datatype
   ``None``) rather than ``Literal("x", datatype=XSD.string)``.

2. **Non-standard RDF**: Graphs with literal predicates (e.g. SHACL
   annotation mode) or relative IRIs (e.g. the metamodel's
   ``bibo:status <testing>``) are rejected by pyoxigraph.  For Turtle,
   N3, TriG, RDF/XML and JSON-LD this function falls back to rdflib's
   serializer, but still canonicalizes blank-node labels and hands rdflib
   the statements in a fixed order, so the fallback output remains
   deterministic across processes.  N-Triples and N-Quads can express
   neither kind of term, so those formats raise ``ValueError`` instead.
   rdflib 7.6 and earlier write an ``rdf:List`` cell shared by two lists
   once per list on this path.

3. **Numeric short forms**: pyoxigraph uses Turtle short forms for
   ``xsd:integer`` (``42``), ``xsd:boolean`` (``true``), and
   ``xsd:decimal`` (``1.23``).  rdflib parses these back with the
   correct datatype, so this is lossless.

4. **Base IRI / prefix collision**: When a graph has ``@base`` and a
   prefix whose namespace equals the base IRI (e.g. rdflib's auto-bound
   ``base:`` prefix), pyoxigraph emits CURIEs like ``base:label`` that
   rdflib rejects.  We skip such prefixes during serialization.

5. **Trailing escaped dot in PN_LOCAL**: pyoxigraph emits CURIEs like
   ``prefix:local\\.`` for IRIs whose local part ends with ``.``.  This
   is valid Turtle (PN_LOCAL_ESC), but rdflib's notation3 parser rejects
   it because it conflicts with the statement-terminator dot.  We
   post-process the output to expand such CURIEs to full ``<IRI>`` form.
"""

import io
import json
import re
import warnings
from collections.abc import Iterator

import pyoxigraph as ox
import rdflib
from rdflib.compare import to_canonical_graph


class RDFCanonicalizationWarning(UserWarning):
    """Issued when ``canonicalize_rdf_graph`` produces output via a degraded path.

    Surfaced via ``warnings.warn`` (not the ``logging`` module) so that it is
    visible by default to both CLI users and library API consumers regardless
    of logging configuration. Filterable with
    ``warnings.filterwarnings("ignore", category=RDFCanonicalizationWarning)``.
    """


# Mapping from rdflib/LinkML format strings to pyoxigraph RdfFormat objects.
_FORMAT_MAP: dict[str, ox.RdfFormat] = {
    "turtle": ox.RdfFormat.TURTLE,
    "ttl": ox.RdfFormat.TURTLE,
    "nt": ox.RdfFormat.N_TRIPLES,
    "ntriples": ox.RdfFormat.N_TRIPLES,
    "n-triples": ox.RdfFormat.N_TRIPLES,
    "nt11": ox.RdfFormat.N_TRIPLES,
    "nquads": ox.RdfFormat.N_QUADS,
    "n-quads": ox.RdfFormat.N_QUADS,
    "xml": ox.RdfFormat.RDF_XML,
    "rdf/xml": ox.RdfFormat.RDF_XML,
    "trig": ox.RdfFormat.TRIG,
    "n3": ox.RdfFormat.N3,
    "json-ld": ox.RdfFormat.JSON_LD,
}

# Formats that support prefix declarations.
_PREFIX_FORMATS = frozenset({ox.RdfFormat.TURTLE, ox.RdfFormat.TRIG, ox.RdfFormat.N3, ox.RdfFormat.RDF_XML})

# Line-oriented formats, which have no syntax for the terms pyoxigraph
# rejects: N-Triples 1.1 section 2.2 admits only absolute IRIs, and a
# predicate must be an IRI.
_LINE_ORIENTED_FORMATS = frozenset({"nt", "ntriples", "n-triples", "nt11", "nquads", "n-quads"})

# An absolute IRI begins with a scheme (RFC 3986 section 3.1).
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


class _SortedGraph(rdflib.Graph):
    """A graph that yields its triples in a fixed order.

    rdflib's serializers write statements, and name unbound namespaces
    ``ns1``, ``ns2``, ..., in the order the store yields triples, which follows
    set iteration and so differs between processes.
    """

    def triples(self, triple: tuple) -> Iterator[tuple]:
        """Yield the triples matching ``triple``, sorted by the N3 form of their terms."""
        yield from sorted(super().triples(triple), key=lambda found: tuple(term.n3() for term in found))


def _iris(graph: rdflib.Graph) -> set[str]:
    """Return the IRIs ``graph`` uses as subject, predicate or object."""
    return {str(term) for triple in graph for term in triple if isinstance(term, rdflib.URIRef)}


def _is_readable_rdf(graph: rdflib.Graph) -> bool:
    """Whether every subject is an IRI or blank node and every predicate an IRI.

    No RDF syntax can express a literal subject or a literal predicate, so
    output written for such a graph cannot be read back.
    """
    return all(isinstance(s, rdflib.URIRef | rdflib.BNode) and isinstance(p, rdflib.URIRef) for s, p, _ in graph)


def _absolute_iris_survive(graph: rdflib.Graph, serialized: str, output_format: str) -> bool:
    """Whether re-reading ``serialized`` yields every absolute IRI of ``graph``.

    rdflib relativizes an IRI against the base by removing the base as a string
    prefix, which is not the inverse of RFC 3986 section 5.2.2: under a base
    ending in ``#`` or inside a path segment, the reference it writes resolves
    to a different IRI.  Resolving the output back is therefore the check.
    Relative IRIs of ``graph`` are left out, because on re-reading they resolve
    against the base, which is what the base is for.
    """
    expected = {iri for iri in _iris(graph) if _ABSOLUTE_IRI.match(iri)}
    return expected <= _iris(rdflib.Graph().parse(data=serialized, format=output_format))


def _deterministic_fallback_serialize(graph: rdflib.Graph, output_format: str) -> str:
    """Serialize a graph that pyoxigraph cannot canonicalize, deterministically.

    pyoxigraph rejects some graphs that rdflib accepts -- notably graphs
    containing relative IRIs (e.g. the metamodel's ``bibo:status <testing>``)
    or literal predicates (SHACL annotation mode).  A plain
    ``graph.serialize()`` for such graphs is *not* reproducible across
    processes: rdflib assigns blank-node labels non-deterministically, and
    writes statements in the order its store yields them.

    To degrade gracefully instead of silently emitting non-deterministic
    output, we canonicalize blank-node labels with rdflib's own
    isomorphism-based canonicalization (:func:`rdflib.compare.to_canonical_graph`,
    which uses a content-derived hash, not run-local ids), hand the statements
    to rdflib in sorted order, and preserve the original prefix bindings that
    the canonical graph drops.

    Relative IRIs are preserved verbatim (not resolved against the base): the
    goal is deterministic output, and silently rewriting ``<testing>`` into an
    absolute IRI would mask what is really a data problem in the source graph.
    The base is kept unless the output would then read back with a different
    absolute IRI, in which case it is dropped with a warning.

    :param graph: The rdflib Graph that pyoxigraph could not parse.
    :param output_format: Target serialization format (e.g. ``"turtle"``).
    :return: Deterministic string serialization of the graph.
    """
    canonical = _SortedGraph()
    canonical += to_canonical_graph(graph)
    # to_canonical_graph builds a fresh graph without the source's namespace
    # bindings; rebind them so the output keeps the source's prefixes.
    for prefix, namespace in graph.namespace_manager.namespaces():
        canonical.namespace_manager.bind(prefix, namespace, replace=True)
    if output_format.lower() == "xml":
        # rdflib's RDF/XML serializer names unbound namespaces while iterating
        # a set of predicates; name them first, in sorted order.
        for predicate in sorted({p for p in canonical.predicates() if isinstance(p, rdflib.URIRef)}):
            canonical.namespace_manager.compute_qname_strict(predicate)
    # A Turtle document is a TriG document whose triples are all in the default
    # graph (TriG section 2.1), where the pyoxigraph path puts them; rdflib's TriG
    # serializer would instead name the graph after a random blank node.
    rdflib_format = "turtle" if output_format.lower() == "trig" else output_format
    canonical.base = graph.base
    serialized = canonical.serialize(format=rdflib_format)
    if graph.base and _is_readable_rdf(graph) and not _absolute_iris_survive(graph, serialized, rdflib_format):
        warnings.warn(
            f"Writing the graph's base IRI {str(graph.base)!r} into {output_format!r} output "
            "would change IRIs that rdflib relativizes against it; serializing without it.",
            RDFCanonicalizationWarning,
            stacklevel=3,
        )
        canonical.base = None
        serialized = canonical.serialize(format=rdflib_format)
    if output_format.lower() == "json-ld":
        # rdflib writes node objects in set order; a JSON-LD array conveys no
        # order unless it is a list (JSON-LD 1.1 section 4.3).
        nodes = sorted(json.loads(serialized), key=lambda node: json.dumps(node, sort_keys=True))
        serialized = json.dumps(nodes, indent=2, ensure_ascii=False)
    return serialized


def _with_single_trailing_newline(text: str) -> str:
    """End ``text`` with exactly one newline, whichever serializer wrote it."""
    return text.rstrip("\n") + "\n"


# Characters that may appear escaped in a Turtle PN_LOCAL via PN_LOCAL_ESC.
_PN_LOCAL_ESC_UNESCAPE = re.compile(r"\\([_~.\-!$&'()*+,;=/?#@%])")


_CURIE_TRAILING_DOT_PATTERN = re.compile(
    r"(?<![<\w])"
    r"([A-Za-z_][\w.-]*?):"
    r"([^\s,;()<>\"'\[\]]*?\\\.)"
    r"(?=\s)"
)


def _iter_turtle_structural_spans(turtle_text: str):
    """Yield ``(start, end, is_structural)`` spans of a Turtle string.

    Structural spans are regions outside of string literals, IRI refs, and
    line comments — i.e. the only places where a CURIE can syntactically
    appear. Non-structural spans (literal contents, IRI bodies, comments)
    are yielded as-is so they round-trip unchanged.

    Handles single- and triple-quoted literals with backslash escapes for
    both ``"`` and ``'`` delimiters, ``<...>`` IRI refs, and ``#...`` line
    comments.
    """
    n = len(turtle_text)
    i = 0
    while i < n:
        ch = turtle_text[i]
        if ch in ('"', "'"):
            # String literal — find matching delimiter, respecting triple-
            # quote form and backslash escapes.
            delim = ch
            triple = turtle_text[i : i + 3] == delim * 3
            end_marker = delim * 3 if triple else delim
            j = i + len(end_marker)
            while j < n:
                if turtle_text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if turtle_text[j : j + len(end_marker)] == end_marker:
                    j += len(end_marker)
                    break
                j += 1
            yield i, j, False
            i = j
        elif ch == "<":
            # IRI ref — find closing '>' on the same logical line.
            j = turtle_text.find(">", i + 1)
            if j == -1:
                yield i, n, False
                i = n
            else:
                yield i, j + 1, False
                i = j + 1
        elif ch == "#":
            # Line comment — to end of line.
            j = turtle_text.find("\n", i)
            j = n if j == -1 else j
            yield i, j, False
            i = j
        else:
            # Structural region — accumulate until the next literal / IRI /
            # comment opener. Treat ``\X`` as a PN_LOCAL_ESC escape (two
            # chars) so that ``\#`` and ``\.`` inside a CURIE local part
            # don't trigger comment / boundary handling.
            start = i
            while i < n:
                c = turtle_text[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c in ('"', "'", "<", "#"):
                    break
                i += 1
            yield start, i, True


def _expand_trailing_dot_curies(turtle_text: str, prefixes: dict[str, str]) -> str:
    """Replace CURIEs whose local part ends in ``\\.`` with full ``<IRI>`` form.

    rdflib's notation3 parser rejects PN_LOCAL ending in an escaped dot
    even though Turtle permits it (PN_LOCAL_ESC). pyoxigraph emits this
    form for IRIs ending in ``.`` (e.g. ``biolink:StrandEnum#.``). We
    rewrite each such CURIE to its expanded ``<IRI>`` form so the output
    round-trips through rdflib.

    The rewrite is applied only to *structural* spans of the document —
    string literals, IRI refs, and comments are left untouched. This is
    what prevents the regex from mangling CURIE-shaped substrings that
    happen to appear inside a literal value.
    """
    if not prefixes:
        return turtle_text

    def replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        local_escaped = match.group(2)
        namespace = prefixes.get(prefix)
        if namespace is None:
            return match.group(0)
        local = _PN_LOCAL_ESC_UNESCAPE.sub(r"\1", local_escaped)
        return f"<{namespace}{local}>"

    parts: list[str] = []
    for start, end, is_structural in _iter_turtle_structural_spans(turtle_text):
        chunk = turtle_text[start:end]
        if is_structural:
            chunk = _CURIE_TRAILING_DOT_PATTERN.sub(replace, chunk)
        parts.append(chunk)
    return "".join(parts)


def _iri_terms(triples: list["ox.Triple"]) -> set[str]:
    """Return the set of IRI strings appearing anywhere in ``triples``.

    Walks subjects, predicates, non-literal objects, and literal datatypes.
    Used to filter the prefix dict down to namespaces that are actually
    referenced by the canonicalized graph, so the output isn't padded with
    unused ``@prefix`` declarations.
    """
    iris: set[str] = set()
    for t in triples:
        for term in (t.subject, t.predicate, t.object):
            if isinstance(term, ox.NamedNode):
                iris.add(term.value)
            elif isinstance(term, ox.Literal):
                dt = term.datatype
                if dt is not None:
                    iris.add(dt.value)
    return iris


def _filter_prefixes_to_used(prefixes: dict[str, str], used_iris: set[str]) -> dict[str, str]:
    """Drop prefix bindings whose namespace is not a prefix of any used IRI.

    A prefix is kept if at least one IRI in ``used_iris`` starts with its
    namespace string. Parent-namespace matches are honored (e.g. a prefix
    bound to ``http://schema.org/`` is kept when ``http://schema.org/Person``
    appears in the graph).
    """
    return {prefix: ns for prefix, ns in prefixes.items() if any(iri.startswith(ns) for iri in used_iris)}


def _is_safe_prefix_iri(iri: str) -> bool:
    """Check whether a namespace IRI is safe for prefix serialization.

    pyoxigraph rejects IRIs with invalid code-points (e.g. double ``#``),
    and rdflib's Turtle parser cannot round-trip CURIEs whose namespace
    contains query parameters or fragments in unexpected positions.  This
    function returns ``False`` for such IRIs so they can be skipped during
    prefix collection.
    """
    # A namespace IRI should end with '/' or '#'.  If '#' appears
    # *before* the final character, the IRI contains an embedded
    # fragment which produces unusable CURIEs.
    if "#" in iri[:-1]:
        return False
    # Query parameters in namespace IRIs produce CURIEs that rdflib
    # cannot parse back.
    if "?" in iri:
        return False
    return True


def canonicalize_rdf_graph(
    graph: rdflib.Graph,
    output_format: str = "turtle",
    diff_stable: bool = False,
) -> str:
    """Serialize an rdflib Graph deterministically using RDFC-1.0 canonicalization.

    The graph is transferred to pyoxigraph via N-Triples, canonicalized
    with RDFC-1.0, sorted, and serialized back to the requested format.
    Prefix bindings from the rdflib Graph are preserved in the output
    for formats that support them (Turtle, TriG, N3, RDF/XML). JSON-LD is
    written in expanded form and indented. A base IRI is declared without
    its fragment, which RFC 3986 section 5.1 strips before resolving
    against a base. Every output ends with exactly one newline.

    Falls back to plain rdflib serialization for unsupported formats or
    graphs containing non-standard RDF (e.g. literal predicates).

    :param graph: The rdflib Graph to serialize.
    :param output_format: Target serialization format (e.g. ``"turtle"``, ``"nt"``).
    :param diff_stable: Use diffable-rdf labels to reduce blank-node churn across
        edits. Requires the ``diff-stable`` extra; disabled by default. The
        non-standard RDF fallback warns when it cannot apply these labels.
        See https://linkml.io/linkml/howtos/collaborative-development.html#rdf-in-version-control
    :return: Deterministic string serialization of the graph.
    :raises TypeError: If ``graph`` can hold named graphs (a ``Dataset`` or
        ``ConjunctiveGraph``), whose graph names one document cannot carry.
    :raises ValueError: If N-Triples or N-Quads are requested for non-standard RDF.
    :raises ImportError: If diff-stable labels are requested without diffable-rdf.
    """
    if graph.context_aware:
        raise TypeError(
            f"canonicalize_rdf_graph serializes a single graph, but got a {type(graph).__name__}, "
            "which holds named graphs; serialize each graph separately."
        )

    if diff_stable:
        try:
            from diffable_rdf import wl_relabel_quads
        except ImportError as exc:
            raise ImportError(
                "diff_stable=True requires diffable-rdf. Install "
                "'linkml-runtime[diff-stable]' or 'linkml[diff-stable]'."
            ) from exc

    ox_format = _FORMAT_MAP.get(output_format.lower())
    if ox_format is None:
        warnings.warn(
            f"pyoxigraph does not support format {output_format!r}; falling back to "
            "rdflib serializer. Output will not be deterministically canonicalized.",
            RDFCanonicalizationWarning,
            stacklevel=2,
        )
        return _with_single_trailing_newline(graph.serialize(format=output_format))

    # 1. Transfer rdflib graph to pyoxigraph via N-Triples.
    nt_data = graph.serialize(format="nt")
    nt_bytes = nt_data.encode("utf-8") if isinstance(nt_data, str) else nt_data

    # 2. Parse into pyoxigraph and build a Dataset for canonicalization.
    #    Fall back to rdflib if the graph contains non-standard RDF
    #    (e.g. literal predicates from annotations) that pyoxigraph rejects.
    try:
        triples = list(ox.parse(io.BytesIO(nt_bytes), format=ox.RdfFormat.N_TRIPLES))
    except SyntaxError as exc:
        # rdflib's N-Triples serialization of this graph is exactly what
        # pyoxigraph's N-Triples parser just rejected.
        if output_format.lower() in _LINE_ORIENTED_FORMATS:
            raise ValueError(
                f"The graph contains terms that {output_format!r} cannot express, such as a "
                f"relative IRI or a literal predicate ({exc}); choose a format such as 'turtle'."
            ) from exc
        warnings.warn(
            "Graph contains non-standard RDF (e.g. relative IRIs or literal predicates) "
            "that pyoxigraph cannot parse; falling back to rdflib. Output is still "
            "deterministic (blank-node labels are canonicalized via rdflib) but is not "
            "canonicalized with pyoxigraph RDFC-1.0.",
            RDFCanonicalizationWarning,
            stacklevel=2,
        )
        if diff_stable:
            warnings.warn(
                "diff_stable=True was requested but this graph took the rdflib fallback, "
                "which cannot apply Weisfeiler-Lehman blank-node labels. Output is "
                "deterministic but NOT diff-stable: an unrelated edit may still renumber "
                "blank nodes. Make the offending terms standard RDF (absolute IRIs, IRI "
                "predicates) to get diff-stable labels.",
                RDFCanonicalizationWarning,
                stacklevel=2,
            )
        return _with_single_trailing_newline(_deterministic_fallback_serialize(graph, output_format))

    dataset = ox.Dataset()
    for triple in triples:
        dataset.add(ox.Quad(triple.subject, triple.predicate, triple.object, ox.DefaultGraph()))

    # 3. Canonicalize blank node labels with RDFC-1.0.
    dataset.canonicalize(ox.CanonicalizationAlgorithm.RDFC_1_0)

    quads = list(dataset)

    if diff_stable:
        quads = wl_relabel_quads(quads)

    # 4. Sort triples for deterministic ordering.
    # RDFC-1.0 stabilizes blank-node labels but pyoxigraph's Dataset
    # iteration order is not sorted and varies across processes (verified
    # empirically against pyoxigraph 0.5.8). The explicit string-key sort
    # is load-bearing for byte-identical output across runs; see
    # tests/linkml_runtime/test_utils/test_rdf_canonicalize.py::test_sort_is_load_bearing.
    sorted_triples = sorted(
        (ox.Triple(q.subject, q.predicate, q.object) for q in quads),
        key=lambda t: (str(t.subject), str(t.predicate), str(t.object)),
    )

    # 5. Collect prefixes for formats that support them.
    base_iri = str(graph.base) if graph.base else None
    prefixes: dict[str, str] | None = None
    if ox_format in _PREFIX_FORMATS:
        prefixes = {}
        for prefix, namespace in graph.namespace_manager.namespaces():
            if not prefix:  # skip empty prefix (base)
                continue
            ns_str = str(namespace)
            # Skip prefixes whose namespace matches the base IRI to avoid
            # pyoxigraph emitting CURIEs like `base:label` that conflict
            # with the @base directive.
            if base_iri and ns_str == base_iri:
                continue
            # Skip namespace IRIs that pyoxigraph rejects or that produce
            # CURIEs rdflib cannot round-trip.  Valid namespace IRIs for
            # prefix use should end with '/' or '#' and contain no query
            # parameters or fragment-like characters in the middle.
            if not _is_safe_prefix_iri(ns_str):
                continue
            prefixes[str(prefix)] = ns_str
        # Drop prefix bindings whose namespace is not referenced by any IRI
        # in the graph. This prevents the rdflib NamespaceManager's default
        # bindings (~30 well-known vocabularies) from being emitted into
        # every output file regardless of whether the schema actually uses
        # them.
        prefixes = _filter_prefixes_to_used(prefixes, _iri_terms(sorted_triples))
    used_prefixes = prefixes
    try:
        result_bytes = ox.serialize(
            sorted_triples,
            format=ox_format,
            prefixes=prefixes,
            base_iri=base_iri.partition("#")[0] if base_iri else None,
        )
    except ValueError as e:
        # pyoxigraph 0.5.x reports rejected prefix IRIs with a message
        # that begins with "Invalid prefix" (verified empirically). Only
        # swallow that case and retry without prefixes — any other
        # ValueError (e.g. invalid base IRI, or an unrelated future
        # serializer bug) must propagate so it surfaces as a stack trace
        # rather than silently dropping all prefix declarations.
        if not str(e).startswith("Invalid prefix"):
            raise
        warnings.warn(
            f"pyoxigraph rejected one or more prefix IRIs ({e}); serializing without "
            "prefix declarations. Output remains canonicalized but is more verbose.",
            RDFCanonicalizationWarning,
            stacklevel=2,
        )
        result_bytes = ox.serialize(
            sorted_triples,
            format=ox_format,
        )
        used_prefixes = None
    result = result_bytes.decode("utf-8")
    if ox_format in _PREFIX_FORMATS and used_prefixes:
        result = _expand_trailing_dot_curies(result, used_prefixes)
    if ox_format == ox.RdfFormat.JSON_LD:
        # pyoxigraph writes JSON-LD on one line, so any edit would rewrite all of it.
        result = json.dumps(json.loads(result), indent=2, ensure_ascii=False)
    return _with_single_trailing_newline(result)
