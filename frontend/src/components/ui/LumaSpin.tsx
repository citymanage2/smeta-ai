import React from 'react';

// size variants via CSS scale — animation stays at 65px, scaled visually
const SCALES = { sm: 0.28, md: 0.55, lg: 0.85 } as const;
type Size = keyof typeof SCALES;

interface LumaSpinProps {
  size?: Size;
  color?: string;
}

export const LumaSpin: React.FC<LumaSpinProps> = ({ size = 'md', color = '#1e293b' }) => {
  const scale = SCALES[size];
  return (
    <div
      style={{
        display: 'inline-block',
        width: 65 * scale,
        height: 65 * scale,
        flexShrink: 0,
      }}
    >
      <div
        style={{
          position: 'relative',
          width: 65,
          height: 65,
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
        }}
      >
        <span
          style={{
            position: 'absolute',
            borderRadius: 50,
            boxShadow: `inset 0 0 0 3px ${color}`,
            animation: 'lumaSpinAnim 2.5s infinite',
          }}
        />
        <span
          style={{
            position: 'absolute',
            borderRadius: 50,
            boxShadow: `inset 0 0 0 3px ${color}`,
            animation: 'lumaSpinAnim 2.5s infinite',
            animationDelay: '-1.25s',
          }}
        />
        <style>{`
          @keyframes lumaSpinAnim {
            0%    { inset: 0 35px 35px 0; }
            12.5% { inset: 0 35px 0 0; }
            25%   { inset: 35px 35px 0 0; }
            37.5% { inset: 35px 0 0 0; }
            50%   { inset: 35px 0 0 35px; }
            62.5% { inset: 0 0 0 35px; }
            75%   { inset: 0 0 35px 35px; }
            87.5% { inset: 0 0 35px 0; }
            100%  { inset: 0 35px 35px 0; }
          }
        `}</style>
      </div>
    </div>
  );
};

// Centered full-area page loader
export const PageLoader: React.FC<{ message?: string }> = ({ message = 'Загрузка...' }) => (
  <div style={{
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    justifyContent: 'center', padding: '64px 24px', gap: 20,
  }}>
    <LumaSpin size="lg" color="#2563eb" />
    <span style={{ fontSize: 14, color: '#94a3b8' }}>{message}</span>
  </div>
);

// Compact loader for sections/modals
export const SectionLoader: React.FC<{ message?: string }> = ({ message = 'Загрузка...' }) => (
  <div style={{
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    justifyContent: 'center', padding: '32px 16px', gap: 14,
  }}>
    <LumaSpin size="md" color="#2563eb" />
    <span style={{ fontSize: 13, color: '#94a3b8' }}>{message}</span>
  </div>
);

// Inline spinner for buttons and status bars (sm size, white or custom color)
export const InlineSpinner: React.FC<{ color?: string }> = ({ color = '#ffffff' }) => (
  <LumaSpin size="sm" color={color} />
);
