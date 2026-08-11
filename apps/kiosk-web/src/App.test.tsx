import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from './App';

describe('Customer Kiosk shell', () => {
  it('renders the application boundary', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Customer Kiosk' })).toBeTruthy();
  });
});
