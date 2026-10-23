from gamebuild.lab.evaluation import summarize_junit, source_fingerprint


def test_fixed_denominator_missing_skipped_failure_and_duplicates(tmp_path):
    xml = tmp_path / 'result.xml'
    xml.write_text('''<testsuites><testsuite>
      <testcase name="test_every_variant_closes_real_loop[01-import]"/>
      <testcase name="test_every_variant_closes_real_loop[01-naming]"><skipped/></testcase>
      <testcase name="test_every_variant_closes_real_loop[01-budget]"><failure message="bad"/></testcase>
      <testcase name="unrelated"/>
    </testsuite></testsuites>''')
    result = summarize_junit(xml)
    assert result['total'] == 41
    assert result['passed'] == 1
    assert result['skipped'] == 1
    assert result['failed'] == 1
    assert result['missing'] == 38
    assert result['rate'] == 1 / 41
    xml.write_text('''<testsuite>
      <testcase name="test_every_variant_closes_real_loop[01-import]"/>
      <testcase name="test_every_variant_closes_real_loop[01-import]"/>
    </testsuite>''')
    result = summarize_junit(xml)
    assert result['passed'] == 0
    assert result['invalid'] == 1


def test_empty_suite_has_no_success_claim(tmp_path):
    xml = tmp_path / 'empty.xml'
    xml.write_text('<testsuite/>')
    result = summarize_junit(xml)
    assert result['passed'] == 0 and result['missing'] == 41


def test_every_variant_has_concrete_teaching_contract():
    from gamebuild.lab.catalog import CASES
    from gamebuild.lab.walkthrough import GUIDES
    for case in CASES:
        guide = GUIDES[case['id']]
        assert set(guide['mutations']) == {v['id'] for v in case['variants']}
        assert all(guide[key] for key in ('target', 'gate', 'repair', 'lesson'))


def test_fingerprint_covers_test_and_execution_sources(tmp_path):
    (tmp_path / 'src/gamebuild').mkdir(parents=True)
    (tmp_path / 'tests').mkdir()
    source = tmp_path / 'src/gamebuild/example.py'
    source.write_text('a')
    test = tmp_path / 'tests/test_lab_scenarios.py'
    test.write_text('a')
    initial = source_fingerprint(tmp_path)
    test.write_text('b')
    assert source_fingerprint(tmp_path) != initial
    changed = source_fingerprint(tmp_path)
    source.write_text('b')
    assert source_fingerprint(tmp_path) != changed


def test_dependency_lock_changes_invalidate_evaluation(tmp_path):
    (tmp_path/'requirements.lock').write_text('example==1')
    before = source_fingerprint(tmp_path)
    (tmp_path/'requirements.lock').write_text('example==2')
    assert source_fingerprint(tmp_path) != before
