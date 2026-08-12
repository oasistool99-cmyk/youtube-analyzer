import pytest

from analyzer.timecode import InvalidTimecode, format_timecode, parse_timecode


@pytest.mark.parametrize(
    "text,expected",
    [
        ("02:35", 155),
        ("00:00", 0),
        ("1:05:10", 3910),
        ("01:05:10", 3910),
        ("90:00", 5400),  # MM:SS에서 분은 60을 넘어도 됩니다.
        ("00:00:05.500", 5),
    ],
)
def test_parse_valid(text, expected):
    assert parse_timecode(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "99:99",  # 초가 60 이상 -> 거부 (기존 정규식은 통과시켰음)
        "01:70:00",
        "01:00:99",
        "abc",
        "",
        "1",
        "1:2:3:4",
    ],
)
def test_parse_invalid(text):
    with pytest.raises(InvalidTimecode):
        parse_timecode(text)


def test_format_roundtrip():
    assert format_timecode(3910) == "01:05:10"
    assert format_timecode(0) == "00:00:00"
    assert format_timecode(-5) == "00:00:00"
