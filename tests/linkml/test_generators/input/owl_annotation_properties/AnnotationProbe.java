import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.formats.TurtleDocumentFormat;
import org.semanticweb.owlapi.io.RDFParserMetaData;
import org.semanticweb.owlapi.model.IRI;
import org.semanticweb.owlapi.model.OWLAnnotationValue;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.profiles.OWL2DLProfile;

/** Check generated artifacts with the pinned OWLAPI, including annotation retention on round-trip. */
class AnnotationProbe {
    private static void verify(OWLOntology ontology, List<String> expectations) {
        var report = new OWL2DLProfile().checkOntology(ontology);
        if (!report.isInProfile()) {
            throw new AssertionError(report.toString());
        }
        if (ontology.signature().anyMatch(entity ->
                entity.getIRI().toString().startsWith("http://org.semanticweb.owlapi/error#"))) {
            throw new AssertionError("Parser recovery entities in ontology");
        }
        var metadata = ontology.getOWLOntologyManager().getOntologyFormat(ontology).getOntologyLoaderMetaData();
        if (metadata.isEmpty() || !(metadata.get() instanceof RDFParserMetaData)) {
            throw new AssertionError("Missing RDF parser diagnostics");
        }
        var rdfMetadata = (RDFParserMetaData) metadata.get();
        if (rdfMetadata.getUnparsedTriples().findAny().isPresent()) {
            throw new AssertionError("Unparsed RDF triples: " + rdfMetadata.getUnparsedTriples().toList());
        }
        var factory = ontology.getOWLOntologyManager().getOWLDataFactory();
        for (var line : expectations) {
            // subject (or 'ontology'), predicate, value kind, value, datatype, language.
            var fields = line.split("\t", -1);
            var property = factory.getOWLAnnotationProperty(IRI.create(fields[1]));
            OWLAnnotationValue value;
            if (fields[2].equals("IRI")) {
                value = IRI.create(fields[3]);
            } else if (!fields[5].isEmpty()) {
                value = factory.getOWLLiteral(fields[3], fields[5]);
            } else if (!fields[4].isEmpty()) {
                value = factory.getOWLLiteral(fields[3], factory.getOWLDatatype(IRI.create(fields[4])));
            } else {
                value = factory.getOWLLiteral(fields[3]);
            }
            boolean retained = fields[0].equals("ontology")
                ? ontology.getAnnotations().contains(factory.getOWLAnnotation(property, value))
                : ontology.containsAxiom(factory.getOWLAnnotationAssertionAxiom(
                    property, IRI.create(fields[0]), value));
            if (!retained) {
                throw new AssertionError("Expected annotation lost: " + line);
            }
        }
    }

    public static void main(String[] args) throws Exception {
        var source = OWLManager.class.getProtectionDomain().getCodeSource().getLocation().toString();
        if (!source.endsWith("/owlapi-distribution-5.5.0.jar")) {
            throw new AssertionError("Unexpected OWLAPI artifact: " + source);
        }
        var manager = OWLManager.createOWLOntologyManager();
        var ontology = manager.loadOntologyFromOntologyDocument(new File(args[0]));
        var expectations = Files.readAllLines(Path.of(args[2]));
        if (expectations.isEmpty()) {
            throw new AssertionError("No annotation expectations supplied");
        }
        verify(ontology, expectations);
        var saved = new File(args[1]);
        manager.saveOntology(ontology, new TurtleDocumentFormat(), IRI.create(saved));
        verify(OWLManager.createOWLOntologyManager().loadOntologyFromOntologyDocument(saved), expectations);
        System.out.println("PASS: OWLAPI 5.5.0; OWL 2 DL; expected annotations survive round-trip");
    }
}
