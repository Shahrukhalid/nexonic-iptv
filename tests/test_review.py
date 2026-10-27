import yaml
from conftest import load_script

from nexonic import review
from nexonic.records import load_records

review_cli = load_script("review")

PENDING_HEADER = "# Candidates awaiting review for DE. See docs/SOURCE_POLICY.md before editing.\n"


def pending_record(record, cid, **kw):
    kw.setdefault("name", cid.title())
    r = record(id=cid, epg_id=cid.title().replace("-", "") + ".de", **kw)
    r["review"].update(status="pending", authorization_basis="none", adult_screening="uncertain", reviewer="intake")
    return r


def setup(tmp_path, record, items, approved=()):
    data = tmp_path / "data"
    for folder in ("approved", "pending", "rejected"):
        (data / folder).mkdir(parents=True)
    # hand-written style: quoted strings, which a re-dump would rewrite
    text = PENDING_HEADER + yaml.safe_dump({"channels": items}, sort_keys=False, allow_unicode=True, width=120)
    text = text.replace("name: Alpha", 'name: "Alpha"')
    (data / "pending" / "de.yaml").write_text(text, encoding="utf-8")
    if approved:
        (data / "approved" / "de.yaml").write_text(
            "# Approved channels for DE. See docs/SOURCE_POLICY.md before editing.\n"
            + yaml.safe_dump({"channels": list(approved)}, sort_keys=False),
            encoding="utf-8",
        )
    return data


def two(record):
    return [
        pending_record(record, "alpha", **{"stream.url": "https://live.alpha-broadcaster.de/a.m3u8"}),
        pending_record(record, "beta", **{"stream.url": "https://live.beta-broadcaster.de/b.m3u8"}),
    ]


def test_list(tmp_path, record):
    data = setup(tmp_path, record, two(record))
    items = review.list_pending(data)
    assert [p.id for p in items] == ["alpha", "beta"]
    assert items[0].file == "pending/de.yaml" and items[0].authorization_basis == "none"


def test_approve_moves_record_and_preserves_the_rest(tmp_path, record):
    data = setup(tmp_path, record, two(record))
    beta_before = (data / "pending" / "de.yaml").read_text(encoding="utf-8")
    dest = review.approve("alpha", "Jane Doe", data, basis="official-broadcaster-stream", confirm_screening=True)
    assert dest == data / "approved" / "de.yaml"
    res = load_records(data)
    assert not res.errors
    assert [c.id for c in res.channels["approved"]] == ["alpha"]
    assert [c.id for c in res.channels["pending"]] == ["beta"]
    ch = res.channels["approved"][0]
    assert ch.review.reviewer == "Jane Doe" and ch.review.status.value == "approved"
    assert ch.review.adult_screening == "pass"
    # new file got the standard header, pending file kept its header and untouched text
    assert dest.read_text(encoding="utf-8").startswith("# Approved channels for DE.")
    left = (data / "pending" / "de.yaml").read_text(encoding="utf-8")
    assert left.startswith(PENDING_HEADER)
    beta_block = beta_before[beta_before.index("- id: beta") :]
    assert left.endswith(beta_block)


def test_approve_appends_without_rewriting_existing_file(tmp_path, record):
    existing = record(id="gamma", name="Gamma", epg_id="Gamma.de", **{"stream.url": "https://live.gamma.de/g.m3u8"})
    data = setup(tmp_path, record, two(record), approved=[existing])
    path = data / "approved" / "de.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("name: Gamma", 'name: "Gamma"'), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    review.approve("beta", "Jane Doe", data, basis="official-broadcaster-stream", confirm_screening=True)
    after = path.read_text(encoding="utf-8")
    assert after.startswith(before)
    assert [c.id for c in load_records(data).channels["approved"]] == ["gamma", "beta"]


def test_approve_needs_basis_and_screening(tmp_path, record):
    data = setup(tmp_path, record, two(record))
    for kw in ({}, {"basis": "official-broadcaster-stream"}, {"confirm_screening": True}):
        try:
            review.approve("alpha", "Jane Doe", data, **kw)
        except review.ReviewError as exc:
            assert "pass" in str(exc) or "basis" in str(exc) or "authorization" in str(exc)
        else:
            raise AssertionError("approval without basis and screening must fail")
    assert [p.id for p in review.list_pending(data)] == ["alpha", "beta"]


def test_approve_refuses_adult_content(tmp_path, record):
    items = [pending_record(record, "erotic-nights", name="Erotic Nights")]
    data = setup(tmp_path, record, items)
    try:
        review.approve("erotic-nights", "Jane Doe", data, basis="official-broadcaster-stream", confirm_screening=True)
    except review.ReviewError as exc:
        assert "cannot approve" in str(exc)
    else:
        raise AssertionError("moderation must block approval")
    assert [p.id for p in review.list_pending(data)] == ["erotic-nights"]
    assert not (data / "approved" / "de.yaml").exists()


def test_automated_records_go_to_auto(tmp_path, record):
    items = [pending_record(record, "alpha", **{"source.method": "automated-domain-match"})]
    data = setup(tmp_path, record, items)
    dest = review.approve("alpha", "Jane Doe", data, basis="official-broadcaster-stream", confirm_screening=True)
    assert dest == data / "approved" / "auto" / "de.yaml"
    assert not load_records(data).errors


def test_community_suggestion_can_be_approved(tmp_path, record):
    items = [pending_record(record, "alpha", **{"source.method": "community-suggestion"})]
    data = setup(tmp_path, record, items)
    review.approve("alpha", "Jane Doe", data, basis="official-broadcaster-stream", confirm_screening=True)
    ch = load_records(data).channels["approved"][0]
    assert ch.source.method == "community-suggestion"


def test_reject_moves_to_country_file_and_deletes_empty_source(tmp_path, record):
    data = setup(tmp_path, record, two(record)[:1])
    dest = review.reject("alpha", "restream, not the broadcaster", "Jane Doe", data)
    assert dest == data / "rejected" / "de.yaml"
    assert dest.read_text(encoding="utf-8").startswith("# Rejected candidates for DE")
    assert not (data / "pending" / "de.yaml").exists()  # no empty files left behind
    res = load_records(data)
    assert not res.errors
    rej = res.channels["rejected"][0]
    assert rej.review.rejection_reason == "restream, not the broadcaster"


def test_reject_needs_reason(tmp_path, record):
    data = setup(tmp_path, record, two(record))
    try:
        review.reject("alpha", "   ", data=data)
    except review.ReviewError:
        pass
    else:
        raise AssertionError("a reason is required")


def test_unknown_id_and_duplicates(tmp_path, record):
    data = setup(tmp_path, record, two(record))
    for fn in (lambda: review.reject("nope", "x", data=data),):
        try:
            fn()
        except review.ReviewError as exc:
            assert "no pending record" in str(exc)
    review.reject("alpha", "no", "Jane Doe", data)
    # second record with the same id in the destination is refused
    again = [pending_record(record, "alpha", **{"stream.url": "https://live.alpha-broadcaster.de/a2.m3u8"})]
    (data / "pending" / "de.yaml").write_text(
        PENDING_HEADER + yaml.safe_dump({"channels": again + [two(record)[1]]}, sort_keys=False), encoding="utf-8"
    )
    before = (data / "pending" / "de.yaml").read_text(encoding="utf-8")
    try:
        review.reject("alpha", "again", "Jane Doe", data)
    except review.ReviewError as exc:
        assert "already exists" in str(exc) or "validation failed" in str(exc)
    assert (data / "pending" / "de.yaml").read_text(encoding="utf-8") == before


def test_rollback_when_validation_fails(tmp_path, record, monkeypatch):
    data = setup(tmp_path, record, two(record))
    snapshot = {p: p.read_text(encoding="utf-8") for p in data.rglob("*.yaml")}
    monkeypatch.setattr(review, "load_records", lambda d: type("R", (), {"errors": [{"error": "forced"}]})())
    try:
        review.reject("alpha", "no", "Jane Doe", data)
    except review.ReviewError as exc:
        assert "rolled back" in str(exc)
    assert {p: p.read_text(encoding="utf-8") for p in data.rglob("*.yaml")} == snapshot
    assert not (data / "rejected" / "de.yaml").exists()


def test_cli(tmp_path, record, monkeypatch, capsys):
    data = setup(tmp_path, record, two(record))
    monkeypatch.setattr(review, "DATA", data)
    monkeypatch.setattr(review, "load_records", lambda d=data: load_records(data))
    assert review_cli.main(["list"]) == 0
    assert "2 pending record(s)." in capsys.readouterr().out
    assert review_cli.main(["approve", "alpha"]) == 1  # no basis / screening on the record
    assert "ERROR" in capsys.readouterr().err
    assert (
        review_cli.main(
            [
                "approve",
                "alpha",
                "--reviewer",
                "Jane Doe",
                "--basis",
                "official-broadcaster-stream",
                "--confirm-screening",
            ]
        )
        == 0
    )
    assert review_cli.main(["reject", "beta", "--reason", "not official"]) == 0
    assert review_cli.main(["reject", "beta", "--reason", "again"]) == 1
    assert review_cli.main(["list"]) == 0
    assert "0 pending record(s)." in capsys.readouterr().out
