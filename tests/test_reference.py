"""Reference tables load correctly and fail loudly when the bundled CSV is broken."""

import pytest

from nexonic.reference import ReferenceDataError, countries, load_countries


def test_bundled_countries_load():
    table = countries()
    assert table["de"]["name"] == "Germany" and table["de"]["flag"]


def test_missing_file_has_clear_error(tmp_path):
    with pytest.raises(ReferenceDataError, match="not found"):
        load_countries(tmp_path / "countries.csv")


def test_missing_column_has_clear_error(tmp_path):
    f = tmp_path / "countries.csv"
    f.write_text("code,name\nde,Germany\n", encoding="utf-8")
    with pytest.raises(ReferenceDataError, match="flag"):
        load_countries(f)


def test_empty_code_rejected(tmp_path):
    f = tmp_path / "countries.csv"
    f.write_text("code,name,flag\n,Germany,x\n", encoding="utf-8")
    with pytest.raises(ReferenceDataError, match="line 2"):
        load_countries(f)
