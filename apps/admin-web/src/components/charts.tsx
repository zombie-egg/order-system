import { useId, useMemo } from 'react';

interface SeriesItem {
  label: string;
  value: number;
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

export function BarChart({
  data,
  formatValue,
  height = 180,
  color = 'var(--accent, #1f7a5c)',
}: {
  data: SeriesItem[];
  formatValue: (value: number) => string;
  height?: number;
  color?: string;
}) {
  const id = useId();
  const maxBucket = useMemo(() => niceMax(Math.max(...data.map((d) => d.value), 1)), [data]);
  const barWidth = 100 / Math.max(data.length, 1);
  const labelCount = Math.min(data.length, 6);
  const labelEvery = Math.max(1, Math.ceil(data.length / labelCount));
  return (
    <div className="chart-wrap" style={{ height }}>
      <svg
        viewBox={`0 0 100 100`}
        preserveAspectRatio="none"
        className="chart-svg"
        role="img"
        aria-label="trend chart"
      >
        <defs>
          <linearGradient id={`${id}-grad`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.85" />
            <stop offset="100%" stopColor={color} stopOpacity="0.35" />
          </linearGradient>
        </defs>
        {data.map((d, index) => {
          const barHeight = (d.value / maxBucket) * 90;
          const x = index * barWidth + barWidth * 0.12;
          const width = barWidth * 0.76;
          return (
            <rect
              key={`${d.label}-${index}`}
              x={x}
              y={95 - barHeight}
              width={width}
              height={barHeight}
              rx="0.6"
              fill={`url(#${id}-grad)`}
            >
              <title>{`${d.label}: ${formatValue(d.value)}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="chart-x-labels">
        {data.map((d, index) => (
          <span
            key={`${d.label}-${index}`}
            className={index % labelEvery === 0 ? '' : 'hidden-label'}
          >
            {d.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function TrendChart({
  data,
  formatValue,
  height = 200,
  color = 'var(--accent, #1f7a5c)',
}: {
  data: SeriesItem[];
  formatValue: (value: number) => string;
  height?: number;
  color?: string;
}) {
  const maxValue = useMemo(() => niceMax(Math.max(...data.map((d) => d.value), 1)), [data]);
  const points = data.map((d, index) => ({
    x: data.length <= 1 ? 0 : (index / (data.length - 1)) * 100,
    y: 92 - (d.value / maxValue) * 84,
    ...d,
  }));
  const linePath = points
    .map((p, index) => `${index === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(' ');
  const areaPath = points.length ? `${linePath} L100,96 L0,96 Z` : '';
  const labelEvery = Math.max(1, Math.ceil(data.length / 6));
  return (
    <div className="chart-wrap" style={{ height }}>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="chart-svg"
        role="img"
        aria-label="trend line"
      >
        {points.length > 0 ? (
          <>
            <path d={areaPath} fill={color} opacity={0.12} />
            <path
              d={linePath}
              fill="none"
              stroke={color}
              strokeWidth="1.4"
              strokeLinejoin="round"
            />
            {points.map((p, i) => (
              <circle key={`pt-${i}`} cx={p.x} cy={p.y} r="1.1" fill={color}>
                <title>{`${p.label}: ${formatValue(p.value)}`}</title>
              </circle>
            ))}
          </>
        ) : null}
      </svg>
      <div className="chart-x-labels">
        {data.map((d, index) => (
          <span
            key={`${d.label}-${index}`}
            className={index % labelEvery === 0 ? '' : 'hidden-label'}
          >
            {d.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function TopNBarList({
  items,
  formatValue,
}: {
  items: { name: string; value: number; detail?: string }[];
  formatValue: (value: number) => string;
}) {
  const max = useMemo(() => niceMax(Math.max(...items.map((i) => i.value), 1)), [items]);
  if (items.length === 0) {
    return <p className="muted standalone-message">—</p>;
  }
  return (
    <ol className="top-n-list">
      {items.map((item, index) => (
        <li key={`${item.name}-${index}`}>
          <span className="top-n-index">{index + 1}</span>
          <div className="top-n-track">
            <span
              className="top-n-bar"
              style={{ width: `${(item.value / max) * 100}%` }}
              title={formatValue(item.value)}
            />
          </div>
          <div className="top-n-labels">
            <strong>{item.name}</strong>
            <span>
              {formatValue(item.value)}
              {item.detail ? ` · ${item.detail}` : ''}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}
