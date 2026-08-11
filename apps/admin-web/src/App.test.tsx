import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from './App';

describe('Admin Dashboard shell', () => {
  it('renders the application boundary', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Admin Dashboard' })).toBeTruthy();
  });
});
