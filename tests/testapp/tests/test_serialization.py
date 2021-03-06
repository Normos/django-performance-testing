import pytest
from django_performance_testing import serializer
from django_performance_testing.signals import results_collected, results_read
from testapp.test_helpers import FakeSender, WithId


def pytest_generate_tests(metafunc):
    if 'collector_cls_with_sample_result' in metafunc.fixturenames:
        plugin_cls_fixtures = metafunc._arg2fixturedefs['collector_cls']
        assert len(plugin_cls_fixtures) == 1
        plugin_cls_fixture = plugin_cls_fixtures[0]
        sample_results = []
        ids = []
        for collector_cls in plugin_cls_fixture.params:
            for i, sample in enumerate(collector_cls.get_sample_results()):
                sample_results.append((collector_cls, sample))
                ids.append('-sample{}-'.format(i))
        metafunc.parametrize(
            argnames='collector_cls_with_sample_result',
            argvalues=sample_results,
            ids=ids
        )


@pytest.fixture
def sample_result(collector_cls, collector_cls_with_sample_result):
    if collector_cls != collector_cls_with_sample_result[0]:
        pytest.skip('this sample result is not for this plugin')
    result = collector_cls_with_sample_result[-1]
    return result


def test_datafile_path_depends_on_setting(settings):
    assert not hasattr(settings, 'DJPT_DATAFILE_PATH'), 'test assumption'
    assert serializer.get_datafile_path() == 'djpt.results_collected'
    settings.DJPT_DATAFILE_PATH = 'foo.log'
    assert serializer.get_datafile_path() == 'foo.log'
    settings.DJPT_DATAFILE_PATH = 'bar'
    assert serializer.get_datafile_path() == 'bar'


def test_writer_writes_collected_results_fired_between_statt_stop(tmpfilepath):
    writer = serializer.Writer(tmpfilepath)
    results_collected.send(
        sender=WithId('before start'), results=[1],
        context={'before': 'start'})
    writer.start()
    results_collected.send(
        sender=WithId('after start'), results=[2],
        context={'after': 'start'})
    writer.end()
    results_collected.send(
        sender=WithId('after end'), results=[3],
        context={'after': 'end'})
    reader = serializer.Reader(tmpfilepath)
    deserialized = reader.read_all()
    assert deserialized == [(WithId('after start'), [2], {'after': 'start'})]
    writer.end()  # dump data again
    reader = serializer.Reader(tmpfilepath)
    deserialized = reader.read_all()
    assert deserialized == \
        [(WithId('after start'), [2], {'after': 'start'})], \
        'after first writer.end it should have disonnected the signal'


def test_writer_only_writes_when_end_is_called(tmpfilepath):
    writer = serializer.Writer(tmpfilepath)
    writer.start()
    results_collected.send(
        sender=WithId('after start'), results=[2],
        context={'after': 'start'})
    reader = serializer.Reader(tmpfilepath)
    deserialized = reader.read_all()
    try:
        assert deserialized == []
    finally:
        writer.end()
    deserialized = reader.read_all()
    assert deserialized == [(WithId('after start'), [2], {'after': 'start'})]


def test_read_all_fires_results_read_signals(tmpfilepath):
    writer = serializer.Writer(tmpfilepath)
    writer.start()
    results_collected.send(
        sender=WithId('after start'), results=[2],
        context={'after': 'start'})
    writer.end()
    results_from_results_read_signal = []

    def record_read_results(sender, results, context, **kwargs):
        results_from_results_read_signal.append((
            sender, results, context
        ))

    results_read.connect(record_read_results)
    reader = serializer.Reader(tmpfilepath)
    deserialized = reader.read_all()
    try:
        assert deserialized != []
        assert results_from_results_read_signal != []
        assert results_from_results_read_signal == deserialized
    finally:
        results_read.disconnect(record_read_results)


@pytest.mark.parametrize('sender_id,sender_type', [
        ('sender_id_1', 'sender_type_1'),
        ('sender_id_2', 'sender_type_2'),
    ])
def test_roundtrip_serialization_single_results(
        tmpfilepath, sender_id, sender_type, sample_result):
    sender = FakeSender(id_=sender_id, type_name=sender_type)
    context = {
        'setUp method': ['setUp (some.module.TestCase'],
    }
    writer = serializer.Writer(tmpfilepath)
    writer.start()
    results_collected.send(
        sender=sender, results=sample_result, context=context)
    writer.end()
    reader = serializer.Reader(tmpfilepath)
    deserialized = reader.read_all()
    assert deserialized == [(sender, sample_result, context)]
