"""PhraseBank — anti-repeat phrase selection with variant support.

Categorised phrase lists, consecutive-repeat avoidance, safe string
formatting against an event context, optional ``:variant`` suffix.

The selection algorithm is deterministic (round-robin) rather than
pseudo-random. The only behavioural promise is
``select()`` never returns the phrase it returned on the previous call
for the same event type when the bank has two or more entries — which
round-robin satisfies trivially while remaining reproducible.
"""

from __future__ import annotations


class _SafeFormatDict(dict):
    """Dict that returns the raw placeholder for missing keys.

    Used with ``str.format_map`` so ``"{missing}".format_map(d)`` yields
    ``"{missing}"`` rather than raising ``KeyError``. Preserves caller
    intent on partially populated contexts.
    """

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


class PhraseBank:
    """Selects phrases from categorised banks with anti-repeat logic.

    Parameters
    ----------
    phrases:
        Mapping of event_type (optionally with ``:variant`` suffix) to
        lists of format-string phrases.
    """

    def __init__(self, phrases: dict[str, list[str]]) -> None:
        self._phrases = phrases
        self._last_index: dict[str, int] = {}

    def select(
        self,
        event_type: str,
        context: dict,
        *,
        variant: str | None = None,
    ) -> str | None:
        """Pick a phrase, format it with *context*, return it.

        Returns ``None`` if *event_type* is unknown or the bank is empty.

        When *variant* is given, the resolver first tries
        ``f"{event_type}:{variant}"``; on miss it falls back to
        *event_type* without the variant suffix.
        """
        # Resolve the phrase list: try variant key first, fall back to base.
        if variant:
            variant_key = f"{event_type}:{variant}"
            bank = self._phrases.get(variant_key)
            if bank is None:
                bank = self._phrases.get(event_type)
        else:
            bank = self._phrases.get(event_type)

        if not bank:
            return None

        if len(bank) == 1:
            idx = 0
        else:
            last = self._last_index.get(event_type, -1)
            idx = (last + 1) % len(bank)

        self._last_index[event_type] = idx
        return bank[idx].format_map(_SafeFormatDict(context))
