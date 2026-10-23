import test from 'node:test';
import assert from 'node:assert/strict';
import { comparisonRows, outcomeTitle } from '../src/gamebuild/lab/web/observations.js';

const before = {checks:[], facts:{issues:[{rule_id:'texture_compression',path:'a',expected:'compressed',actual:'none'}]}};
test('failed verification retains actual values and newly introduced violations', () => {
  const after = {passed:false,checks:[],facts:{issues:[
    {rule_id:'texture_compression',path:'a',expected:'compressed',actual:'still-none'},
    {rule_id:'asset_too_large',path:'b',expected:256,actual:1024},
  ]}};
  const rows=comparisonRows(before,after);
  assert.equal(rows.length,2);
  assert.equal(rows[0].after,'still-none');
  assert.equal(rows[1].after,1024);
  assert.equal(rows[0].fixed,false);
});
test('historical missing observations never imply repaired or crash', () => {
  const after={passed:true,checks:[],facts:{}};
  assert.equal(comparisonRows(before,after)[0].fixed,false);
  assert.match(comparisonRows(before,after)[0].after,/缺少/);
  assert.match(outcomeTitle(before,after,true,false),/缺少/);
});
test('failed checks introduced during verification are included', () => {
  const rows=comparisonRows({checks:[{label:'compile',passed:false,expected:0,actual:1}]},
    {checks:[{label:'compile',passed:true,expected:0,actual:0},{label:'runtime',passed:false,expected:0,actual:2}]});
  assert.equal(rows.length,2);
  assert.equal(rows[1].after,2);
});
