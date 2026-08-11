"""Regression tests for two compounding ElnBaseSection.normalize() bugs hit by
generated entries in production.

1. AttributeError: ElnBaseSection.normalize() (nomad.datamodel.metainfo.eln)
   falls back to `archive.metadata.entry_name.split('.')...` whenever a
   section's `name` is unset. Column-mode generated entries didn't set `name`
   and archive.metadata.entry_name wasn't populated yet at that point either,
   so this crashed with AttributeError: 'NoneType' object has no attribute
   'split'. Fixed by having schema_generation.build_entry_dict set `name`
   explicitly (see test_build_entry_dict_sets_a_nonempty_name below).

2. RecursionError: fixing (1) by only setting `name` surfaced a second, worse
   bug - our generated base_sections listed ElnBaseSection *last*
   (`[EntryData, TableData, PlotSection, ElnBaseSection]`), whereas NOMAD's
   own convention has it *first* (see BasicEln(ElnBaseSection, EntryData) in
   nomad.datamodel.metainfo.eln). ElnBaseSection.normalize() explicitly
   re-invokes `EntryData.normalize(self, ...)`; that call's own `super()` is
   resolved against the instance's full MRO, so with EntryData before
   ElnBaseSection, that second call chains straight back into
   ElnBaseSection.normalize() again - infinite recursion, confirmed
   empirically (not just theoretically) while diagnosing bug 1's fix. Fixed
   by listing ElnBaseSection first in base_sections.

These tests exercise the real nomad-lab ElnBaseSection.normalize(), not just
our own dict-shape assertions, so this exact regression can't slip through
schema_generation-only unit tests again.
"""

import importlib

import pytest
import yaml
from nomad.datamodel.data import EntryData
from nomad.datamodel.datamodel import EntryArchive, EntryMetadata
from nomad.datamodel.metainfo.eln import ElnBaseSection

from nomad_auto_upload_tables.parsers.tabular_guess import TabularGuessParser
from nomad_auto_upload_tables.schema_generation import build_entry_dict, build_generated_artifacts
from nomad_auto_upload_tables.schema_packages.tabular_guess import TabularGuess

from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'


class _CorrectOrder(ElnBaseSection, EntryData):
    """Minimal stand-in matching NOMAD's own required order: ElnBaseSection
    first, EntryData after."""


class _WrongOrder(EntryData, ElnBaseSection):
    """The order this plugin used to generate; reproduces the recursion bug."""


def test_wrong_order_with_name_set_recurses_infinitely():
    """Documents bug 2: EntryData-before-ElnBaseSection recurses even once
    `name` is set (i.e. bug 1's fix alone isn't sufficient)."""
    section = _WrongOrder(name='Zellstoff Daten')
    archive = EntryArchive(data=section, metadata=EntryMetadata())

    with pytest.raises(RecursionError):
        section.normalize(archive, logger=None)


def test_unset_name_and_entry_name_reproduces_bug_1():
    section = _CorrectOrder()
    archive = EntryArchive(data=section, metadata=EntryMetadata())

    with pytest.raises(AttributeError):
        section.normalize(archive, logger=None)


def test_correct_order_with_name_set_normalizes_cleanly():
    section = _CorrectOrder(name='Zellstoff Daten')
    archive = EntryArchive(data=section, metadata=EntryMetadata())

    section.normalize(archive, logger=None)  # must not raise

    assert archive.metadata.entry_name == 'Zellstoff Daten'


def test_build_entry_dict_sets_a_nonempty_name():
    entry = build_entry_dict(
        schema_file='generated_schemas/zellstoff_daten_schema.archive.yaml',
        entry_file='generated_entries/zellstoff_daten_entry.archive.yaml',
        section_name='ZellstoffDaten',
        data_file='zellstoff_daten.xlsx',
    )

    assert entry['data']['name'] == 'Zellstoff Daten'


def _import_class(dotted_path: str):
    module_path, _, class_name = dotted_path.rpartition('.')
    return getattr(importlib.import_module(module_path), class_name)


def test_real_generated_schema_base_sections_normalize_without_recursion(tmp_path):
    """End-to-end guard: build the *actual* base_sections list schema_generation
    produces for a column-mode entry, construct a real Python class with that
    exact MRO, and normalize() it - so any future base_sections reordering
    that reintroduces the recursion trap fails this test immediately."""
    filename = 'sample.csv'
    raw_file = tmp_path / filename
    raw_file.write_bytes((DATA_DIR / filename).read_bytes())

    class _Context:
        def __init__(self, raw_dir):
            self.raw_dir = Path(raw_dir)

        def raw_path(self):
            return str(self.raw_dir)

        def raw_path_exists(self, path):
            return (self.raw_dir / path).exists()

        def raw_file(self, path, mode='rb', *args, **kwargs):
            target = self.raw_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            return open(target, mode)

        def process_updated_raw_file(self, path, allow_modify=False):
            pass

    class _Archive:
        def __init__(self, raw_dir, data=None):
            self.data = data
            self.m_context = _Context(raw_dir)
            self.metadata = None

    archive = _Archive(tmp_path)
    TabularGuessParser().parse(str(raw_file), archive)
    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'sample_review.archive.yaml').read_text())
    entry = TabularGuess.m_from_dict(review['data'])
    entry.confirm_schema = True

    artifacts = build_generated_artifacts(entry)
    schema = yaml.safe_load(artifacts.schema_yaml)
    section = schema['definitions']['sections'][artifacts.section_name]
    base_section_classes = tuple(_import_class(path) for path in section['base_sections'])

    GeneratedLike = type('GeneratedLike', base_section_classes, {})
    instance = GeneratedLike(name='Sample')
    real_archive = EntryArchive(data=instance, metadata=EntryMetadata())

    instance.normalize(real_archive, logger=None)  # must not raise/recurse

    assert real_archive.metadata.entry_name == 'Sample'
