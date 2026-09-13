import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const buttonVariants = cva(
  'inline-flex cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-neutral-950 text-white hover:bg-neutral-900',
        destructive: 'bg-red-700 text-white hover:bg-red-800',
        outline: 'border border-neutral-400 bg-white/30 text-neutral-950',
        secondary: 'bg-white/45 text-neutral-950',
        ghost: 'bg-transparent text-neutral-950',
        link: 'bg-transparent text-neutral-950 underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 px-3 text-xs',
        lg: 'h-10 px-8',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return <Comp ref={ref} className={cn(buttonVariants({ variant, size, className }))} {...props} />;
  },
);
Button.displayName = 'Button';

const liquidbuttonVariants = cva(
  'relative inline-flex cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium outline-none transition-[color,box-shadow,transform,filter] disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-transparent text-neutral-950 hover:scale-105',
        destructive: 'bg-red-700/85 text-white',
        outline: 'border border-neutral-500/50 bg-white/20 text-neutral-950',
        secondary: 'bg-white/25 text-neutral-950',
        ghost: 'bg-transparent text-neutral-950',
        link: 'bg-transparent text-neutral-950 underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 px-4 text-xs',
        lg: 'h-10 px-6',
        xl: 'h-12 px-8',
        xxl: 'h-14 px-10',
        icon: 'size-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'xxl' },
  },
);

export function LiquidButton({
  className,
  variant,
  size,
  asChild = false,
  children,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof liquidbuttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'button';
  return (
    <Comp className={cn(liquidbuttonVariants({ variant, size, className }))} {...props}>
      <span className="liquid-glass-surface" aria-hidden="true" />
      <span className="liquid-glass-label">{children}</span>
    </Comp>
  );
}

export function GlassFilter() {
  return (
    <svg className="liquid-glass-filter" aria-hidden="true">
      <defs>
        <filter id="container-glass" x="0%" y="0%" width="100%" height="100%" colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency="0.05 0.05" numOctaves="1" seed="1" result="turbulence" />
          <feGaussianBlur in="turbulence" stdDeviation="2" result="blurredNoise" />
          <feDisplacementMap in="SourceGraphic" in2="blurredNoise" scale="70" xChannelSelector="R" yChannelSelector="B" result="displaced" />
          <feGaussianBlur in="displaced" stdDeviation="4" result="finalBlur" />
          <feComposite in="finalBlur" in2="finalBlur" operator="over" />
        </filter>
      </defs>
    </svg>
  );
}

// The variant exports intentionally mirror the shadcn component API.
// eslint-disable-next-line react-refresh/only-export-components
export { buttonVariants, liquidbuttonVariants };
