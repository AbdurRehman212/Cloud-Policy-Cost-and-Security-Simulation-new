import { safeRedirect } from './safeRedirect';

test('keeps same-site paths', () => {
  expect(safeRedirect('/remediation')).toBe('/remediation');
  expect(safeRedirect('/audit?category=auth#top')).toBe('/audit?category=auth#top');
});

test.each([
  ['https://evil.example'],
  ['//evil.example'],
  ['/\\evil.example'], // GHSA-wrjc-x8rr-h8h6: backslash is treated as a slash by browsers
  ['\\\\evil.example'],
  ['/\tevil.example'],
  ['javascript:alert(1)'],
  [''],
  [null],
  [undefined],
  ['/' + 'x'.repeat(600)],
])('rejects %p', (target) => {
  expect(safeRedirect(target)).toBe('/');
});
