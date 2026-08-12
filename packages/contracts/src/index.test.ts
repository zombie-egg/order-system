import { describe, expect, it } from 'vitest';
import { formatMinorUnits } from './index';

describe('formatMinorUnits', () => {
  it('formats integer minor units without floating point input at the boundary', () => {
    expect(formatMinorUnits(1295, 'EUR', 'nl-NL')).toContain('12,95');
  });
});
