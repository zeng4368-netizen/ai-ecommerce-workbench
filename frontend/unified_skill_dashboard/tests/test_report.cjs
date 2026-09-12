const assert=require('node:assert/strict');const R=require('../assets/report.js');
assert.ok(!R.render('<script>alert(1)</script>').includes('<script>'));
assert.ok(R.render('# Title\n| A | B |\n|---|---|\n| 1 | 2 |').includes('<table>'));
assert.ok(!R.render('[click](javascript:alert(1))').includes('<a'));
console.log('Safe report renderer passed.');
