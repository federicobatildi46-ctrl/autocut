from pathlib import Path

import pytest

from autocut.paths import ProjectNameError, project_dir
from autocut.timeparse import RangeError, parse_range, parse_time_ms


@pytest.mark.parametrize(
    ("text", "ms"),
    [("60", 60000), ("62.5", 62500), ("1:00", 60000), ("1:02.25", 62250), ("1:00:00", 3600000)],
)
def test_parse_time(text, ms):
    assert parse_time_ms(text) == ms


@pytest.mark.parametrize("text", ["", "a", "1:75", "-5", "1::2", "1:2:3:4"])
def test_parse_time_rejects(text):
    with pytest.raises(RangeError):
        parse_time_ms(text)


def test_parse_range():
    r = parse_range("1:00-3:00")
    assert (r.start_ms, r.end_ms) == (60000, 180000)
    with pytest.raises(RangeError):
        parse_range("180-60")
    with pytest.raises(RangeError):
        parse_range("60")


def test_range_runs_get_their_own_folder(tmp_path):
    root = Path(tmp_path)
    assert project_dir("episodio-12", root=root) == root / "episodio-12"
    assert (
        project_dir("episodio-12", parse_range("60-182.5"), root=root)
        == root / "episodio-12__range_60-182.5"
    )


@pytest.mark.parametrize("name", ["", "../fuori", "a/b", " spazio", "x__range_1-2"])
def test_invalid_project_names(name, tmp_path):
    with pytest.raises(ProjectNameError):
        project_dir(name, root=tmp_path)
