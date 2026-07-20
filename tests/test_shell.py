from xaas.util import shell


def _testcase(obj: shell.Command, expected_text: str) -> None:
    assert obj.to_shell(False) == expected_text


def test_command_escape() -> None:
    # don't escape simple string
    _testcase(
        shell.SimpleCommand(["echo", "fizzbuzz"]),
        "echo fizzbuzz")

    # escape whitespace
    _testcase(
        shell.SimpleCommand(["echo", "hello world"]),
        "echo 'hello world'")

    # escape single quotes
    _testcase(
        shell.SimpleCommand(["echo", "'"]),
        # this is pretty silly but that's simply what shlex.quote("'") does
        "echo ''\"'\"''")

    # don't escape other special symbols
    _testcase(
        shell.SimpleCommand(["echo", '"', "$"]),
        "echo '\"' '$'")


def test_expandable() -> None:
    # properly quote parameter expansions
    _testcase(
        shell.SimpleCommand([shell.Parameter("ECHO"), "fizzbuzz"]),
        '"$ECHO" fizzbuzz')

    # properly deal with concatenating different types of expandables
    _testcase(
        shell.SimpleCommand(["echo", shell.Concat([
            'Path to C++ compiler: "',
            shell.Parameter("CXX"),
            '"',
        ])]),
        "echo 'Path to C++ compiler: \"'\"$CXX\"'\"'")


def test_command_assignment() -> None:
    # test multiple assignments
    _testcase(
        shell.SimpleCommand(
            ["env"],
            assignments={
                "foo": "bar",
                "bar": "baz",
                "MSG": '"Hello world!"',
            }),
        "foo=bar bar=baz MSG='\"Hello world!\"' env")

    # test expansion in assignments
    _testcase(
        shell.SimpleCommand(
            ["echo", "fizzbuzz"],
            assignments={
                "PATH": shell.Concat([
                    "/usr/local/bin:",
                    shell.Parameter("PATH"),
                ])
            }),
        'PATH=/usr/local/bin:"$PATH" echo fizzbuzz')


def test_redirect() -> None:
    # test simple input/output redirect
    _testcase(
        shell.SimpleCommand(
            ["cat"],
            redirects=[
                shell.InputRedirect("input data.txt"),
                shell.OutputRedirect(shell.Concat([
                    shell.Parameter("OUTDIR"), "/out.txt",
                ])),
            ]),
        'cat < \'input data.txt\' > "$OUTDIR"/out.txt')

    # test single redirect with non-default settings
    _testcase(
        shell.SimpleCommand(
            ["cat"],
            redirects=shell.InputRedirect("in.txt", fd=1)),
        'cat 1< in.txt')

    _testcase(
        shell.SimpleCommand(
            ["cat"],
            redirects=shell.OutputRedirect("out.txt", fd=2)),
        'cat 2> out.txt')

    _testcase(
        shell.SimpleCommand(
            ["cat"],
            redirects=shell.OutputRedirect("out.txt", fd=2, append=True)),
        'cat 2>> out.txt')

    # test redirects on subshells and groups
    _testcase(
        shell.Subshell(
            shell.ListAnd([
                shell.SimpleCommand(["echo", "1"]),
                shell.SimpleCommand(["echo", "2"]),
            ]),
            redirects=shell.OutputRedirect("out.txt", append=True)),
        "( echo 1 && echo 2 ) >> out.txt")
    _testcase(
        shell.Group(
            shell.ListAnd([
                shell.SimpleCommand(["echo", "1"]),
                shell.SimpleCommand(["echo", "2"]),
            ]),
            redirects=shell.OutputRedirect("out.txt", append=True)),
        "{ echo 1 && echo 2; } >> out.txt")


def test_pipeline() -> None:
    # test simple pipeline
    _testcase(
        shell.Pipeline([
            shell.SimpleCommand(["seq", "1", "10"]),
            shell.SimpleCommand(["xargs", "echo"]),
            shell.SimpleCommand(["cksum"]),
        ]),
        "seq 1 10 | xargs echo | cksum")


def test_nested_command_list() -> None:
    # nested lists with same operator shouldn't be grouped
    _testcase(
        shell.ListAnd([
            shell.SimpleCommand(["echo", "a"]),
            shell.ListAnd([
                shell.SimpleCommand(["echo", "b"]),
                shell.SimpleCommand(["echo", "c"]),
            ]),
        ]),
        "echo a && echo b && echo c")

    _testcase(
        shell.ListOr([
            shell.SimpleCommand(["echo", "a"]),
            shell.ListOr([
                shell.SimpleCommand(["echo", "b"]),
                shell.SimpleCommand(["echo", "c"]),
            ]),
        ]),
        "echo a || echo b || echo c")

    # nested lists with different operator should be grouped
    _testcase(
        shell.ListAnd([
            shell.SimpleCommand(["echo", "a"]),
            shell.ListOr([
                shell.SimpleCommand(["echo", "b"]),
                shell.SimpleCommand(["echo", "c"]),
            ]),
        ]),
        "echo a && { echo b || echo c; }")

    _testcase(
        shell.ListOr([
            shell.SimpleCommand(["echo", "a"]),
            shell.ListAnd([
                shell.SimpleCommand(["echo", "b"]),
                shell.SimpleCommand(["echo", "c"]),
            ]),
        ]),
        "echo a || { echo b && echo c; }")
