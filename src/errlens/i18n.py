"""Installed-package JSON catalogs with simple, validated named placeholders."""

import json
from importlib.resources import files
from string import Formatter

from errlens.models import Parameter

DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = ("ru", "en")


def validate_template(template: str) -> frozenset[str]:
    """Accept {name} fields and escaped braces, reject expressions/specifiers."""
    names: set[str] = set()
    for _, name, specification, conversion in Formatter().parse(template):
        if name is None:
            continue
        if not name.isidentifier() or specification or conversion:
            raise ValueError(f"Invalid named placeholder in template: {template!r}")
        names.add(name)
    return frozenset(names)


def load_catalog(locale: str) -> dict[str, str]:
    """Load and validate one supported catalog, without filesystem cwd lookup."""
    if locale not in SUPPORTED_LOCALES:
        raise ValueError(f"Unsupported locale: {locale}")
    resource = files("errlens").joinpath("locales", f"{locale}.json")
    data: object = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Translation catalog must be an object")
    catalog: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key or not isinstance(value, str):
            raise ValueError("Translation keys must be nonempty strings and values strings")
        validate_template(value)
        catalog[key] = value
    return catalog


class Translator:
    """Fallback: selected locale -> Russian -> literal key.

    Unsupported locales and missing template parameters raise ValueError.
    A missing key is returned literally, without formatting untrusted key text.
    """

    def __init__(self, locale: str = DEFAULT_LOCALE) -> None:
        self.locale = locale
        self._catalog = load_catalog(locale)
        self._fallback = load_catalog(DEFAULT_LOCALE)

    def translate(self, key: str, **parameters: Parameter) -> str:
        template = self._catalog.get(key, self._fallback.get(key))
        if template is None:
            return key
        missing = validate_template(template).difference(parameters)
        if missing:
            raise ValueError(f"Missing translation parameters: {', '.join(sorted(missing))}")
        return template.format_map(parameters)
