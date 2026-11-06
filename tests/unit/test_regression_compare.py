"""Regression comparison of pytest runs before and after refactoring (Lab 8)."""

import pytest

from scripts import regression_compare as rc

pytestmark = pytest.mark.req("QA-20")


def junit(**cases: str) -> str:
    """Create pytest-style JUnit XML from module__test keys."""
    body = {
        "passed": "",
        "failed": "<failure message='boom'/>",
        "error": "<error message='setup'/>",
        "skipped": "<skipped message='no db'/>",
    }
    rows = "".join(
        f'<testcase classname="{key.split("__")[0]}" name="{key.split("__")[1]}">'
        f"{body[outcome]}</testcase>"
        for key, outcome in cases.items()
    )
    return (
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{rows}</testsuite></testsuites>'
    )


def test_outcomes_are_read_per_test_id():
    xml = junit(a__ok="passed", a__bad="failed", b__err="error", b__skip="skipped")
    assert rc.outcomes(xml) == {
        "a::ok": "passed",
        "a::bad": "failed",
        "b::err": "error",
        "b::skip": "skipped",
    }


def test_same_tests_with_same_results_is_a_clean_regression_run():
    before = rc.outcomes(junit(a__one="passed", a__two="passed"))
    text, clean = rc.report(before, dict(before))
    assert clean
    assert text.endswith("Регресій немає.\n")


def test_added_characterization_tests_are_listed_but_allowed():
    before = rc.outcomes(junit(a__one="passed"))
    after = rc.outcomes(junit(a__one="passed", c__pinned="passed"))
    text, clean = rc.report(before, after)
    assert clean
    assert "Нові тести (для інформації): 1\n  c::pinned\n" in text


@pytest.mark.parametrize(
    ("after", "group"),
    [
        ({"a__one": "passed"}, "removed"),
        ({"a__one": "passed", "a__two": "failed"}, "degraded"),
        ({"a__one": "passed", "a__two": "skipped"}, "degraded"),
        ({"a__one": "passed", "a__two": "passed", "c__new": "error"}, "failing"),
    ],
)
def test_lost_degraded_or_failing_tests_are_regressions(after, group):
    before = rc.outcomes(junit(a__one="passed", a__two="passed"))
    groups = rc.compare(before, rc.outcomes(junit(**after)))
    assert groups[group]
    assert rc.report(before, rc.outcomes(junit(**after)))[1] is False


def test_test_that_was_already_skipped_is_not_a_regression():
    before = rc.outcomes(junit(a__one="skipped"))
    assert rc.report(before, dict(before))[1] is True


def test_cli_reports_and_sets_the_exit_code(tmp_path, capsys):
    before, after = tmp_path / "before.xml", tmp_path / "after.xml"
    before.write_text(junit(a__one="passed", a__two="passed"), encoding="utf-8")
    after.write_text(junit(a__one="passed", a__two="passed"), encoding="utf-8")
    assert rc.main([str(before), str(after)]) == 0
    assert "До: тестів 2 — passed 2 · failed 0 · error 0 · skipped 0" in capsys.readouterr().out
    after.write_text(junit(a__one="passed"), encoding="utf-8")
    assert rc.main([str(before), str(after)]) == 1
    after.write_text("<not-xml", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        rc.main([str(before), str(after)])
    assert exit_info.value.code == 2


def test_cli_rejects_path_outside_working_directory(tmp_path, monkeypatch):
    working = tmp_path / "working"
    working.mkdir()
    outside = tmp_path / "outside.xml"
    outside.write_text(junit(a__one="passed"), encoding="utf-8")
    monkeypatch.chdir(working)
    with pytest.raises(SystemExit) as error:
        rc.main([str(outside), str(outside)])
    assert error.value.code == 2


def test_cli_rejects_symlink_to_external_xml(tmp_path, monkeypatch):
    working = tmp_path / "working"
    working.mkdir()
    outside = tmp_path / "outside.xml"
    outside.write_text(junit(a__one="passed"), encoding="utf-8")
    (working / "linked.xml").symlink_to(outside)
    monkeypatch.chdir(working)
    with pytest.raises(SystemExit) as error:
        rc.main(["linked.xml", "linked.xml"])
    assert error.value.code == 2
