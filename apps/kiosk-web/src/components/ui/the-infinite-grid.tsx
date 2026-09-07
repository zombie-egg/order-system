import { type PropsWithChildren, useEffect, useRef } from 'react';
import {
  motion,
  type MotionValue,
  useAnimationFrame,
  useMotionTemplate,
  useMotionValue,
} from 'framer-motion';
import { cn } from '../../lib/utils';

interface InfiniteGridProps extends PropsWithChildren {
  className?: string;
}

interface InfiniteGridBackdropProps {
  idPrefix?: string;
}

/**
 * The visual layer from the Infinite Grid reference, adapted as a non-blocking
 * application background so the existing kiosk workflow remains fully interactive.
 */
export function InfiniteGrid({ children, className }: InfiniteGridProps) {
  return (
    <div className={cn('infinite-grid-root', className)}>
      <InfiniteGridBackdrop />
      <div className="infinite-grid-content">{children}</div>
    </div>
  );
}

export function InfiniteGridBackdrop({ idPrefix = 'kiosk-grid' }: InfiniteGridBackdropProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);
  const gridOffsetX = useMotionValue(0);
  const gridOffsetY = useMotionValue(0);

  useEffect(() => {
    const centerPointer = () => {
      mouseX.set(window.innerWidth / 2);
      mouseY.set(window.innerHeight / 2);
    };
    const trackPointer = (event: PointerEvent) => {
      mouseX.set(event.clientX);
      mouseY.set(event.clientY);
    };
    centerPointer();
    window.addEventListener('pointermove', trackPointer, { passive: true });
    window.addEventListener('resize', centerPointer);
    return () => {
      window.removeEventListener('pointermove', trackPointer);
      window.removeEventListener('resize', centerPointer);
    };
  }, [mouseX, mouseY]);

  useAnimationFrame(() => {
    gridOffsetX.set((gridOffsetX.get() + 0.5) % 40);
    gridOffsetY.set((gridOffsetY.get() + 0.5) % 40);
  });

  const maskImage = useMotionTemplate`radial-gradient(300px circle at ${mouseX}px ${mouseY}px, black, transparent)`;

  return (
    <div ref={containerRef} className="infinite-grid-backdrop">
      <div className="infinite-grid-base" aria-hidden="true">
        <GridPattern offsetX={gridOffsetX} offsetY={gridOffsetY} patternId={`${idPrefix}-base`} />
      </div>
      <motion.div
        className="infinite-grid-active"
        style={{ maskImage, WebkitMaskImage: maskImage }}
        aria-hidden="true"
      >
        <GridPattern offsetX={gridOffsetX} offsetY={gridOffsetY} patternId={`${idPrefix}-active`} />
      </motion.div>
      <div className="infinite-grid-glows" aria-hidden="true">
        <span className="infinite-grid-glow infinite-grid-glow-orange" />
        <span className="infinite-grid-glow infinite-grid-glow-primary" />
        <span className="infinite-grid-glow infinite-grid-glow-blue" />
      </div>
    </div>
  );
}

function GridPattern({
  offsetX,
  offsetY,
  patternId,
}: {
  offsetX: MotionValue<number>;
  offsetY: MotionValue<number>;
  patternId: string;
}) {
  return (
    <svg className="infinite-grid-pattern" focusable="false">
      <defs>
        <motion.pattern
          id={patternId}
          width="40"
          height="40"
          patternUnits="userSpaceOnUse"
          x={offsetX}
          y={offsetY}
        >
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="currentColor" strokeWidth="1" />
        </motion.pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${patternId})`} />
    </svg>
  );
}

export const Component = InfiniteGrid;
