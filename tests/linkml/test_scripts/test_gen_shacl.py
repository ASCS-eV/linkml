from click.testing import CliRunner

from linkml.generators.shaclgen import cli


def test_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "Generate SHACL turtle from a LinkML model" in result.output


_RULES_SCHEMA_FOR_CLI = """\
id: https://example.org/cli-test
name: cli_test
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/cli-test/
imports:
  - linkml:types
default_prefix: ex
default_range: string
slots:
  Flag:
    range: boolean
    slot_uri: ex:Flag
  flagValue:
    range: decimal
    slot_uri: ex:flagValue
classes:
  TestClass:
    class_uri: ex:TestClass
    slots:
      - Flag
      - flagValue
    rules:
      - description: If flagValue present, Flag must be true.
        preconditions:
          slot_conditions:
            flagValue:
              value_presence: PRESENT
        postconditions:
          slot_conditions:
            Flag:
              equals_string: "true"
"""


def test_emit_rules_flag():
    """--no-emit-rules suppresses sh:sparql in CLI output."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("schema.yaml", "w") as f:
            f.write(_RULES_SCHEMA_FOR_CLI)

        result_with = runner.invoke(cli, ["schema.yaml", "--emit-rules"])
        assert result_with.exit_code == 0, result_with.output
        assert "sh:sparql" in result_with.output

        result_without = runner.invoke(cli, ["schema.yaml", "--no-emit-rules"])
        assert result_without.exit_code == 0, result_without.output
        assert "SPARQLConstraint" not in result_without.output
