import pytest

from nexonic import config
from nexonic.checker import Limits


def test_defaults_match_the_values_the_scripts_always_used():
    cfg = config.PipelineConfig()
    lim = Limits()
    assert cfg.verify.timeout == lim.timeout == 10.0
    assert cfg.verify.concurrency == lim.concurrency == 12
    assert cfg.verify.retries == lim.retries == 1
    assert cfg.verify.backoff_base == lim.backoff_base == 1.0
    assert cfg.verify.per_host_interval == lim.per_host_interval == 1.0
    assert cfg.verify.channel_timeout == lim.channel_timeout == 60.0
    assert cfg.verify.budget_minutes * 60 == lim.run_budget
    assert cfg.verify.max_concurrency == 16


def test_shipped_file_equals_the_defaults(monkeypatch):
    monkeypatch.delenv("NEXONIC_PIPELINE_CONFIG", raising=False)
    assert config.load_pipeline(config.PIPELINE_FILE) == config.PipelineConfig()


def test_missing_file_gives_defaults(tmp_path):
    assert config.load_pipeline(tmp_path / "nope.toml") == config.PipelineConfig()


def test_partial_file_overrides_only_named_keys(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text("[quarantine]\nconsecutive_failures = 5\n[guard]\nmax_drop_percent = 2\n", encoding="utf-8")
    cfg = config.load_pipeline(f)
    assert cfg.quarantine.consecutive_failures == 5
    assert cfg.quarantine.distinct_days == 2
    assert cfg.guard.max_drop_percent == 2.0
    assert cfg.verify == config.VerifyConfig()


def test_env_var_selects_file(tmp_path, monkeypatch):
    f = tmp_path / "p.toml"
    f.write_text("[verify]\nconcurrency = 3\n", encoding="utf-8")
    monkeypatch.setenv("NEXONIC_PIPELINE_CONFIG", str(f))
    assert config.load_pipeline().verify.concurrency == 3


@pytest.mark.parametrize(
    "text",
    [
        "[verfy]\ntimeout = 1\n",  # unknown section
        "[verify]\ntimeoutt = 1\n",  # unknown key
        "[verify]\ntimeout = 'fast'\n",  # wrong type
        "[quarantine]\nconsecutive_failures = 0\n",  # must be positive
        "[guard]\nmax_drop_percent = 150\n",
        "[guard]\noverride = 'yes'\n",
        "[[discovery.sources]]\nname = 'x'\n",
        "[verify\n",
    ],
)
def test_bad_config_is_rejected(tmp_path, text):
    f = tmp_path / "p.toml"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load_pipeline(f)


def test_guard_override_flag_and_env(monkeypatch):
    monkeypatch.delenv("NEXONIC_GUARD_OVERRIDE", raising=False)
    assert not config.guard_override(config.GuardConfig())
    assert config.guard_override(config.GuardConfig(override=True))
    monkeypatch.setenv("NEXONIC_GUARD_OVERRIDE", "1")
    assert config.guard_override(config.GuardConfig())
