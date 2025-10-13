"""Helpers for deriving Madden Companion identifiers for a specific game year."""

from __future__ import annotations

from dataclasses import dataclass

# Suffixes used by EA for the X-BLAZE-ID header. The "gen" suffix maps to the
# hardware generation nomenclature the companion app expects.
_HEADER_SUFFIX = {
    "xbsx": "xbsx-gen5",
    "xbox": "xbsx-gen5",
    "xbox-series": "xbsx-gen5",
    "ps5": "ps5-gen5",
    "playstation": "ps5-gen5",
    "playstation5": "ps5-gen5",
    "pc": "pc-gen5",
    "steam": "pc-gen5",
    "origin": "pc-gen5",
    "windows": "pc-gen5",
    "xone": "xone-gen4",
    "ps4": "ps4-gen4",
}

# Entitlement suffixes used when validating licenses via EA's OAuth flows.
_ENTITLEMENT_SUFFIX = {
    "xbsx": "XBSX",
    "xbox": "XBSX",
    "xbox-series": "XBSX",
    "ps5": "PS5",
    "playstation": "PS5",
    "playstation5": "PS5",
    "pc": "PC",
    "steam": "PC",
    "origin": "PC",
    "windows": "PC",
    "xone": "XONE",
    "ps4": "PS4",
}

_DEFAULT_PLATFORM = "xbsx"


def _normalise_platform(platform: str | None) -> str:
    if not platform:
        return _DEFAULT_PLATFORM
    normalised = platform.strip().lower()
    return normalised if normalised in _HEADER_SUFFIX else _DEFAULT_PLATFORM


@dataclass(frozen=True)
class MaddenIdentifiers:
    """Materialised identifiers for a Madden game year/platform."""

    year: int
    platform: str

    @property
    def blaze_header(self) -> str:
        suffix = _HEADER_SUFFIX[self.platform]
        return f"madden-{self.year}-{suffix}"

    @property
    def product_name(self) -> str:
        return f"madden-{self.year}-{self.platform}-mca"

    @property
    def service_slug(self) -> str:
        return f"madden-{self.year}-{self.platform}"

    @property
    def entitlement_code(self) -> str:
        suffix = _ENTITLEMENT_SUFFIX[self.platform]
        year_suffix = str(self.year)[-2:]
        return f"MADDEN_{year_suffix}{suffix}"


def get_identifiers(year: int, platform: str | None = None) -> MaddenIdentifiers:
    """Return precomputed identifiers for the supplied Madden cycle."""

    normalised = _normalise_platform(platform)
    return MaddenIdentifiers(year=year, platform=normalised)


__all__ = ["MaddenIdentifiers", "get_identifiers"]
