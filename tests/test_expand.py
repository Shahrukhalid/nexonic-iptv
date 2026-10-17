import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
import expand_catalog as ec  # noqa: E402


@pytest.mark.parametrize(
    "host,website,ok",
    [
        ("live.france24.com", "https://www.france24.com/en/", True),
        ("canli.tgrthaber.com", "https://www.tgrthaber.com.tr", True),
        ("tv-trtworld.medya.trt.com.tr", "https://www.trt.net.tr", False),  # 3-letter label too weak; curated
        ("cdn-euronews.akamaized.net", "https://www.euronews.com", True),
        ("stream.camara.gov.br", "https://www.camara.gov.br", True),
        ("cdn-7.pishow.tv", "https://www.aljazeera.com", False),
        ("d1234abcd.cloudfront.net", "https://www.cbc.ca", False),
        ("someone.akamaized.net", "https://www.dw.com", False),  # short label never matched on shared CDNs
        ("tv.example.co.uk", "https://other.co.uk", False),  # public suffix is not an owner
        ("news.bbc.co.uk", "https://www.bbc.co.uk", True),
    ],
)
def test_owner_match(host, website, ok):
    assert (ec.owner_match(host, website) is not None) is ok


def test_registrable():
    assert ec.registrable("a.b.example.com.br") == "example.com.br"
    assert ec.registrable("live.france24.com") == "france24.com"


def test_aggregators_excluded():
    assert ec.AGGREGATOR_HOSTS.search("amg01234-x.amagi.tv")
    assert ec.AGGREGATOR_HOSTS.search("service-stitcher.clusters.pluto.tv")
    assert not ec.AGGREGATOR_HOSTS.search("live.france24.com")
