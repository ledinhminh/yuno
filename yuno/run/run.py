import os
import posixpath
import re
import sys

from yuno import core
from yuno.core import testing, errors, util
from yuno.core.config import config

import cli
import diff_routines


def _build_regex_filter(regex):
    regex = re.compile(regex)

    def filter_function(test_case):
        return re.match(test_case.source.path)

    return filter_function


# TODO: This function was designed before the diff feature was added. Having to
# pass [options] sucks.
def _run_tests(options, test_set=None, glob=None):
    def pause_controller(test_result):
        if test_result in (options.pause_on or []):
            raw_input("Paused. Press Enter to continue.\n")


    if glob is not None:
        test_set = core.testing.load_from_glob(glob)

    harness = core.testing.Harness(
        diff_routine=diff_routines.__dict__.get(options.diff_mode),
        pause_controller=pause_controller if options.pause_on else None
    )
    harness.run_set(test_set or [])

    return (harness, test_set)


def _run_regex(options, pattern):
    """Runs every test in the repo whose path matches [pattern]. Expects a
    compiled regex.

    TODO: Expose this via --regex flag.
    """
    test_set = core.testing.load_all(
        filter_fn=(lambda test: pattern.match(test.source.path))
    )

    return _run_tests(options, test_set=test_set)


def _run_all(options):
    """$ yuno run all
    """
    print "Running all tests in %s\n" % config.test_folder
    return _run_tests(
        options, test_set=core.testing.load_all()
    )


def _run_glob(options):
    """$ yuno run <glob>
    """
    print "Running tests in {} and subfolders:\n".format(options.glob)

    glob = options.glob.strip()
    return _run_tests(
        options, glob=posixpath.join(glob, '**', '*' + config.source_extension)
    )


def _run_pipe(options):
    """$ <stream> | yuno run -
    """
    print "Running tests from pipe:\n"

    test_set = core.testing.load_from_file(sys.stdin)
    return _run_tests(options, test_set=test_set)


def _run_phase(options):
    """$ yuno run phase <#>
    """
    print "Running phase %s:\n" % options.phase
    options.check = '*'
    return _run_phase_and_check(options)


def _run_check(options):
    """$ yuno run check <#>
    """
    print "Running check %s:\n" % options.check
    options.phase = '*'
    return _run_phase_and_check(options)


def _run_phase_and_check(options):
    """$ yuno run phase <#> check <#>
    """
    phase = options.phase.strip() if options.phase else '*'
    check = options.check.strip() if options.check else '*'
    invalid_glob_range = re.compile(r'\d{2,}-\d+|\d+-\d{2,}')
    valid_arg = re.compile(r'^\d+(-\d+)?$|^\*$')

    # Keep the * option undocumented. It's a quirk and not particularly helpful.
    if not valid_arg.match(phase) or not valid_arg.match(check):
        raise core.errors.YunoError('Phase/check must be <#> or <from>-<to>.')

    # Strictly speaking, real globs allow only single-character ranges like
    # '5-9'. To support more useful ranges like '5-20', branch off to search the
    # repo with a regex filter if the glob expander can't handle what was given.
    if invalid_glob_range.match(phase) or invalid_glob_range.match(check):
        regex = core.testing.build_regex(phase=phase, check=check)
        return _run_regex(options, regex)
    else:
        glob = core.testing.build_glob(phase=phase, check=check)
        return _run_tests(options, glob=glob)


def _run_failed(options):
    """$ yuno run failed
    """
    # Let main() deal with any errors raised in here.
    # Right now some non-Yuno errors (IOErrors, etc) will just dump traces.

    print "Running tests that failed last time:\n"

    with open('data/last-run.txt') as last_run:
        failed_tests = re.findall(r'^f (.*)$', last_run.read(), re.MULTILINE)
        test_set = [core.testing.Test(t) for t in failed_tests if t.strip()]

    return _run_tests(options, test_set=test_set)


def _run_failing(options):
    """$ yuno run failing
    """
    print "Running all tests currently failing:\n"
    return _run_suite(options, filename='data/failing.txt')


def _run_files(options):
    """$ yuno run files <glob>
    """
    print "Running any test that matches {}:\n".format(options.files)
    return _run_tests(options, glob=options.files.strip())


def _run_suite(options, filename=None):
    """$ yuno run suite <name>
    """
    if filename is None:
        suite_name = options.suite.strip()
        suite = core.testing.Suite.from_name(suite_name)
        print "Running {0} ({1.filename}):\n".format(suite_name, suite)

    else:
        suite = core.testing.Suite.from_file(filename)

    return _run_tests(options, test_set=suite.tests)


def _save_suite(name, tests, overwrite=False):
    filename = posixpath.join(config.suite_folders[0], name + '.txt')

    if os.path.isfile(filename) and not overwrite:
        print "\nSuite %s already exists. Use --save %s -o to overwrite." % (
            name, name
        )
        return

    try:
        core.testing.Suite(name, filename, tests).save()
        print "\nSaved these tests as %s (%s.txt)." % (
            name, posixpath.join(config.suite_folders[0], name)
        )
    except core.errors.SuiteSaveError as e:
        print e.for_console()
        print "Please try again or check the permissions."


def _display_results(harness):
    num_passed = len(harness.passed)
    num_failed = len(harness.failed)
    num_skipped = len(harness.skipped)
    num_warned = len(harness.warned)
    num_regressions = len(harness.regressions)
    num_fixes = len(harness.fixes)
    total = num_passed + num_failed + num_skipped

    print "=" * 80
    print "Ran %d tests\n" % total
    print "  %d passed" % num_passed
    print "  %d failed" % num_failed

    if num_failed > 0:
        print "      View?   yuno.py show failed"
        print "      Re-run? yuno.py run failed"
        # note about diff files goes here

    if num_skipped > 0:
        print "  %d skipped" % num_skipped
        print "      View? yuno.py show skipped"

    if num_warned > 0:
        print "  %d warned" % num_warned
        print "      View? yuno.py show warned"

    if num_regressions > 0:
        print "\n- %d %s\n   " % (
            num_regressions,
            util.nice_plural(num_regressions, 'regression', 'regressions')
        ),
        print "\n    ".join([str(test) for test in sorted(harness.regressions)])

    if num_fixes > 0:
        print "\n+ %d fixed :)\n   " % num_fixes,
        print "\n    ".join([str(test) for test in sorted(harness.fixes)])


def main(argv=sys.argv):
    options, parser = cli.get_cli_args(argv)

    if options.command is None:
        parser.print_help()
        sys.exit(2)

    command_handlers = {
        cli.RUN_ALL: _run_all,
        cli.RUN_FAILED: _run_failed,
        cli.RUN_FAILING: _run_failing,
        cli.RUN_GLOB: _run_glob,
        cli.RUN_PHASE: _run_phase,
        cli.RUN_CHECK: _run_check,
        cli.RUN_PHASE_AND_CHECK: _run_phase_and_check,
        cli.RUN_SUITE: _run_suite,
        cli.RUN_FILES: _run_files,
        cli.RUN_PIPE: _run_pipe
    }

    try:
        harness, test_set = command_handlers[options.command](options)
        _display_results(harness)

        if options.save_as:
            _save_suite(options.save_as, test_set, overwrite=options.overwrite)

    except core.errors.SuiteLoadError as e:
        print e.for_console()
        print "To see what suites are available, use:"
        print "    yuno.py show suites"

    except core.errors.EmptyTestSet as e:
        print e.for_console()

        if options.command == cli.RUN_GLOB:
            print "To run specific tests, use:"
            print "    yuno.py run files path/to/test*.rc"
        # TODO: this.
        # elif options.command == cli.RUN_SUITE:
        #     print "To see its contents, use:"
        #     print "    yuno.py show suite {}".format(options.suite)

    except core.errors.YunoError as e:
        print e.for_console()

    except KeyboardInterrupt:
        print "Run stopped."