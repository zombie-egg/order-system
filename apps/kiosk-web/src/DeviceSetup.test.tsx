import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_API_BASE_URL } from './api';
import { DeviceSetup } from './DeviceSetup';

describe('DeviceSetup', () => {
  it('only asks for the store kiosk ID and key while using the configured API internally', () => {
    const onConfigured = vi.fn();
    render(<DeviceSetup onConfigured={onConfigured} />);

    expect(screen.queryByText('Edge API-adres')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Kiosk-ID van deze vestiging')).toBeInTheDocument();
    expect(screen.getByLabelText('Kiosk-sleutel')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Kiosk-ID van deze vestiging'), {
      target: { value: 'kiosk-id' },
    });
    fireEvent.change(screen.getByLabelText('Kiosk-sleutel'), {
      target: { value: 'kiosk-secret' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Verbinden' }));

    expect(onConfigured).toHaveBeenCalledWith({
      apiBaseUrl: DEFAULT_API_BASE_URL,
      kioskId: 'kiosk-id',
      kioskKey: 'kiosk-secret',
    });
  });
});
