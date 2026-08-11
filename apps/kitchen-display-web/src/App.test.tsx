import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from './App';

describe('Kitchen Display shell', () => {
  it('renders the application boundary', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Kitchen Display' })).toBeTruthy();
  });
});
