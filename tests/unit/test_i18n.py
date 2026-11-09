"""Catalog loading, fallback and safe template grammar."""

import pytest

from errlens.i18n import Translator, load_catalog, validate_template


def test_catalogs_have_matching_keys_and_parameters() -> None:
    russian, english = load_catalog("ru"), load_catalog("en")
    assert russian.keys() == english.keys()
    for key in russian:
        assert validate_template(russian[key]) == validate_template(english[key])


def test_default_and_substitution() -> None:
    assert Translator().locale == "ru"
    assert Translator().translate("cli.version", version="0.1.0") == "ErrLens 0.1.0"
    assert "not implemented" in Translator("en").translate("cli.run_pending")


def test_missing_translation_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from errlens import i18n

    catalogs = {"ru": {"fallback": "Русский {name}"}, "en": {}}
    monkeypatch.setattr(i18n, "load_catalog", lambda locale: catalogs[locale])
    translator = Translator("en")
    assert translator.translate("fallback", name="текст") == "Русский текст"
    assert translator.translate("missing.{untrusted}") == "missing.{untrusted}"


def test_missing_parameters() -> None:
    with pytest.raises(ValueError, match="version"):
        Translator().translate("cli.version")


def test_unsupported_locale() -> None:
    with pytest.raises(ValueError, match="Unsupported locale"):
        Translator("../secret")


@pytest.mark.parametrize("template", ["{", "}", "{}", "{0}", "{x.value}", "{x[0]}",
                                      "{x!r}", "{x:>10}", "{x:{width}}"])
def test_invalid_template(template: str) -> None:
    with pytest.raises(ValueError):
        validate_template(template)


def test_escaped_braces() -> None:
    assert validate_template("{{literal}} {name}") == frozenset({"name"})


@pytest.mark.parametrize("content", ['[]', '{"key": 1}', '{"": "value"}', '{"key": "{"}'])
def test_invalid_catalog(content: str, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from errlens import i18n

    directory = tmp_path / "locales"
    directory.mkdir()
    (directory / "ru.json").write_text(content, encoding="utf-8")
    monkeypatch.setattr(i18n, "files", lambda package: tmp_path)
    with pytest.raises(ValueError):
        load_catalog("ru")
