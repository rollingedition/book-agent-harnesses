from unitcraft.cli import main


def test_wrong_arguments_exit_with_2(capsys):
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_convert_exits_with_0(capsys):
    assert main(["convert", "2", "kg", "kg"]) == 0
