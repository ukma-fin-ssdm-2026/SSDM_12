from scripts.check_lab06 import debug_stages_valid


def test_expected_red_green_sequence_is_valid():
    stages = [
        {"stage": "red", "exit_code": 1},
        {"stage": "green", "exit_code": 0},
    ]

    assert debug_stages_valid(stages) is True
