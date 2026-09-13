import type React from 'react';
import { cn } from '../../lib/utils';

interface BorderBeamProps { className?: string; size?: number; duration?: number; borderWidth?: number; anchor?: number; colorFrom?: string; colorTo?: string; delay?: number }
export function BorderBeam({ className, size = 200, duration = 15, anchor = 90, borderWidth = 1.5, colorFrom = '#ffaa40', colorTo = '#9c40ff', delay = 0 }: BorderBeamProps) {
  return <div aria-hidden="true" style={{ '--size': size, '--duration': duration, '--anchor': anchor, '--border-width': borderWidth, '--color-from': colorFrom, '--color-to': colorTo, '--delay': `-${delay}s` } as React.CSSProperties} className={cn('pointer-events-none absolute inset-0 rounded-[inherit] [border:calc(var(--border-width)*1px)_solid_transparent]', className)} />;
}
