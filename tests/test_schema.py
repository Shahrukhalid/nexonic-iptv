import pytest
from pydantic import ValidationError

from nexonic.models import Channel
from nexonic.records import load_records


def test_valid_record(record):
    ch = Channel.model_validate(record())
    assert ch.country == "de" and ch.languages == ["de"] and ch.primary_category == "news"


@pytest.mark.parametrize(
    "override",
    [
        {"country": "zz"},
        {"country": "germany"},
        {"languages": ["xx"]},
        {"languages": []},
        {"categories": ["xxx"]},  # adult categories do not exist in the schema
        {"categories": ["adult"]},
        {"categories": []},
        {"id": "Bad_ID"},
        {"id": "-x"},
        {"stream.url": "https://example.com/a b.m3u8"},
        {"unexpected_field": 1},
        {"epg_id": "bad id!"},
    ],
)
def test_invalid_records(record, override):
    with pytest.raises(ValidationError):
        Channel.model_validate(record(**override))


def test_approved_requires_authorization(record):
    rec = record()
    rec["review"]["authorization_basis"] = "none"
    with pytest.raises(ValidationError, match="authorization_basis"):
        Channel.model_validate(rec)


def test_approved_requires_adult_screening_pass(record):
    rec = record()
    rec["review"]["adult_screening"] = "uncertain"
    with pytest.raises(ValidationError, match="adult_screening"):
        Channel.model_validate(rec)


def test_nsfw_can_never_be_approved(record):
    with pytest.raises(ValidationError, match="adult-oriented"):
        Channel.model_validate(record(is_nsfw=True))


def test_rejected_requires_reason(record):
    rec = record()
    rec["review"].update(status="rejected", authorization_basis="none")
    with pytest.raises(ValidationError, match="rejection_reason"):
        Channel.model_validate(rec)


def test_unknown_metadata_is_explicit(record):
    rec = record()
    rec["geo"] = {"restricted": "unknown", "regions": []}
    ch = Channel.model_validate(rec)
    assert ch.geo.restricted == "unknown" and ch.stream.quality == "unknown"


def test_folder_status_mismatch_is_error(dataset, record):
    rec = record()
    rec["review"]["status"] = "pending"
    data = dataset([rec])
    res = load_records(data)
    assert any("does not match folder" in e["error"] for e in res.errors)


def test_country_file_must_match(dataset, record):
    data = dataset([record()])
    (data / "approved" / "de.yaml").rename(data / "approved" / "fr.yaml")
    res = load_records(data)
    assert any("must live in approved/de.yaml" in e["error"] for e in res.errors)


def test_repository_data_is_valid():
    res = load_records()
    assert res.errors == []
    assert len(res.approved) > 0


def test_community_suggestion_method_validates(record):
    pending = record(**{"source.method": "community-suggestion"})
    pending["review"].update(status="pending", authorization_basis="none", adult_screening="uncertain")
    ch = Channel.model_validate(pending)
    assert ch.source.method == "community-suggestion"
    assert not ch.automated  # never treated as an automated admission


def test_unknown_source_method_rejected(record):
    with pytest.raises(ValidationError):
        Channel.model_validate(record(**{"source.method": "scraped"}))


def test_community_suggestion_in_pending_folder_loads(dataset, record):
    pending = record(**{"source.method": "community-suggestion"})
    pending["review"].update(status="pending", authorization_basis="none", adult_screening="uncertain")
    res = load_records(dataset([], [pending]))
    assert not res.errors and len(res.channels["pending"]) == 1
