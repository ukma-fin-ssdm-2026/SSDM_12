import pytest

from scripts.check_lab06 import debug_stages_valid


def test_expected_red_green_sequence_is_valid():
    stages = [
        {"stage": "red", "exit_code": 1},
        {"stage": "green", "exit_code": 0},
    ]

    assert debug_stages_valid(stages) is True


@pytest.mark.parametrize(
    "stages",
    [
        [{"stage": "green", "exit_code": 1}, {"stage": "red", "exit_code": 0}],
        [{"exit_code": 1}, {"stage": "green", "exit_code": 0}],
        [{"stage": "red", "exit_code": 2}, {"stage": "green", "exit_code": 0}],
        [{"stage": "red", "exit_code": 1}],
        [{"stage": "red", "exit_code": 1}, {"stage": "green", "exit_code": 0}, {}],
        None,
        [{"stage": "red", "exit_code": 1}, None],
    ],
)
def test_wrong_debug_sequences_are_rejected(stages):
    assert debug_stages_valid(stages) is False
